import os
import re
import time

import requests


class SteamService:
    def __init__(self, logger=None):
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def friendly_api_error(self, error=None, response=None):
        if response is None and error is not None:
            response = getattr(error, "response", None)

        status = getattr(response, "status_code", None)
        if status in (401, 403):
            return "access denied (check Steam Web API key and account permissions)"
        if status == 429:
            return "rate limited by Steam Web API"
        if status and status >= 500:
            return f"Steam service unavailable (HTTP {status})"
        if status:
            return f"HTTP {status}"

        if error is None:
            return "unknown API error"

        name = error.__class__.__name__.lower()
        if "timeout" in name:
            return "request timed out"
        if "connection" in name:
            return "network connection failed"
        return str(error)

    def request_with_retry(self, method, url, operation_name="request", timeout=10, attempts=3, backoff=1.0, **kwargs):
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                response = requests.request(method=method, url=url, timeout=timeout, **kwargs)
                if response.status_code in (429,) or response.status_code >= 500:
                    if attempt < attempts:
                        self.log(f"{operation_name} failed ({self.friendly_api_error(response=response)}). Retrying ({attempt}/{attempts})...")
                        time.sleep(backoff * (2 ** (attempt - 1)))
                        continue
                response.raise_for_status()
                return response
            except Exception as e:
                last_error = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status and status not in (429,) and status < 500:
                    raise
                if attempt >= attempts:
                    raise
                self.log(f"{operation_name} failed ({self.friendly_api_error(e)}). Retrying ({attempt}/{attempts})...")
                time.sleep(backoff * (2 ** (attempt - 1)))

        if last_error:
            raise last_error
        raise RuntimeError(f"{operation_name} failed.")

    def vdf_escape(self, value):
        text = str(value if value is not None else "")
        text = text.replace("\\", "\\\\")
        text = text.replace("\"", "\\\"")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\n", "\\n")
        return text

    def build_upload_vdf_content(self, appid, publishedfileid, contentfolder, previewfile, visibility, title, description, changenote):
        values = {
            "appid": self.vdf_escape(appid),
            "publishedfileid": self.vdf_escape(publishedfileid),
            "contentfolder": self.vdf_escape(os.path.abspath(contentfolder)),
            "previewfile": self.vdf_escape(os.path.abspath(previewfile)),
            "visibility": self.vdf_escape(visibility),
            "title": self.vdf_escape(title),
            "description": self.vdf_escape(description),
            "changenote": self.vdf_escape(changenote),
        }
        return (
            "\"workshopitem\"\n"
            "{\n"
            f"    \"appid\" \"{values['appid']}\"\n"
            f"    \"publishedfileid\" \"{values['publishedfileid']}\"\n"
            f"    \"contentfolder\" \"{values['contentfolder']}\"\n"
            f"    \"previewfile\" \"{values['previewfile']}\"\n"
            f"    \"visibility\" \"{values['visibility']}\"\n"
            f"    \"title\" \"{values['title']}\"\n"
            f"    \"description\" \"{values['description']}\"\n"
            f"    \"changenote\" \"{values['changenote']}\"\n"
            "}\n"
        )

    def tokenize_vdf(self, text):
        tokens = []
        i = 0
        length = len(text)

        while i < length:
            ch = text[i]
            if ch.isspace():
                i += 1
                continue

            if ch == "/" and i + 1 < length and text[i + 1] == "/":
                i += 2
                while i < length and text[i] not in ("\r", "\n"):
                    i += 1
                continue

            if ch in "{}":
                tokens.append(ch)
                i += 1
                continue

            if ch == "\"":
                i += 1
                value = []
                while i < length:
                    current = text[i]
                    if current == "\\" and i + 1 < length:
                        nxt = text[i + 1]
                        escapes = {"n": "\n", "r": "\r", "t": "\t", "\"": "\"", "\\": "\\"}
                        value.append(escapes.get(nxt, nxt))
                        i += 2
                        continue
                    if current == "\"":
                        i += 1
                        break
                    value.append(current)
                    i += 1
                tokens.append(("STRING", "".join(value)))
                continue

            start = i
            while i < length and (not text[i].isspace()) and text[i] not in "{}":
                i += 1
            tokens.append(("STRING", text[start:i]))

        return tokens

    def parse_vdf_tokens(self, tokens, start_index=0, expect_closing=False):
        data = {}
        i = start_index

        while i < len(tokens):
            token = tokens[i]
            if token == "}":
                if expect_closing:
                    return data, i + 1
                raise ValueError("Unexpected closing brace in VDF.")

            if token == "{":
                raise ValueError("Unexpected opening brace in VDF.")

            key = token[1]
            i += 1
            if i >= len(tokens):
                raise ValueError("Missing VDF value after key.")

            next_token = tokens[i]
            if next_token == "{":
                value, i = self.parse_vdf_tokens(tokens, i + 1, expect_closing=True)
            else:
                value = next_token[1]
                i += 1
            data[key] = value

        if expect_closing:
            raise ValueError("Missing closing brace in VDF.")
        return data, i

    def parse_vdf_text(self, text):
        tokens = self.tokenize_vdf(text)
        parsed, _ = self.parse_vdf_tokens(tokens)
        return parsed

    def dict_get_ci(self, dct, key, default=""):
        if not isinstance(dct, dict):
            return default
        for current_key, value in dct.items():
            if str(current_key).lower() == key.lower():
                return value
        return default

    def resolve_vanity_to_steamid(self, vanity, api_key, retry_kwargs=None):
        retry_kwargs = retry_kwargs or {}
        url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
        response = self.request_with_retry(
            "GET",
            url,
            operation_name="Resolve vanity URL",
            params={"key": api_key, "vanityurl": vanity},
            timeout=10,
            **retry_kwargs,
        )
        data = response.json().get("response", {})
        if data.get("success") == 1:
            return data.get("steamid")
        return None

    def resolve_steam_id(self, identity_input, api_key, retry_kwargs=None):
        text = (identity_input or "").strip()
        if not text:
            return None

        if text.isdigit() and len(text) == 17:
            return text

        profiles_match = re.search(r"steamcommunity\.com/profiles/(\d{17})", text, re.IGNORECASE)
        if profiles_match:
            return profiles_match.group(1)

        vanity = text
        vanity_match = re.search(r"steamcommunity\.com/id/([^/?#]+)", text, re.IGNORECASE)
        if vanity_match:
            vanity = vanity_match.group(1)
        else:
            vanity = re.sub(r"^https?://", "", vanity, flags=re.IGNORECASE).strip().strip("/")
            if vanity.lower().startswith("id/"):
                vanity = vanity[3:].strip("/")

        if vanity:
            try:
                return self.resolve_vanity_to_steamid(vanity, api_key, retry_kwargs=retry_kwargs)
            except Exception:
                return None
        return None

    def extract_loginusers_accounts(self, vdf_path):
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        parsed = self.parse_vdf_text(content)
        users = self.dict_get_ci(parsed, "users", {})
        if not isinstance(users, dict):
            return []

        accounts = []
        for steam_id, info in users.items():
            if not (str(steam_id).isdigit() and len(str(steam_id)) == 17):
                continue
            accounts.append({
                "steamid": str(steam_id),
                "account_name": str(self.dict_get_ci(info, "AccountName", "")).strip(),
                "persona_name": str(self.dict_get_ci(info, "PersonaName", "")).strip(),
                "most_recent": str(self.dict_get_ci(info, "MostRecent", "")).strip(),
            })
        return accounts

    def detect_local_steam_identity(self, steamcmd_exe="", base_dir=""):
        candidates = []

        if steamcmd_exe:
            candidates.append(os.path.join(os.path.dirname(steamcmd_exe), "config", "loginusers.vdf"))

        for env_var in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            base = os.environ.get(env_var, "")
            if base:
                candidates.append(os.path.join(base, "Steam", "config", "loginusers.vdf"))

        if base_dir:
            candidates.append(os.path.join(base_dir, "steamcmd", "config", "loginusers.vdf"))

        seen = set()
        for path in candidates:
            norm = os.path.normpath(path)
            if norm in seen or not os.path.exists(norm):
                continue
            seen.add(norm)
            try:
                accounts = self.extract_loginusers_accounts(norm)
                if not accounts:
                    continue
                accounts.sort(key=lambda a: (a.get("most_recent") != "1", a.get("account_name", "")))
                account = accounts[0]
                account["source"] = norm
                return account
            except Exception:
                continue
        return None

    def begin_qr_auth_session(self, device_friendly_name, platform_type=1, timeout=10):
        url = "https://api.steampowered.com/IAuthenticationService/BeginAuthSessionViaQR/v1/"
        response = requests.post(
            url,
            data={
                "device_friendly_name": device_friendly_name,
                "platform_type": platform_type,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("response", {})

    def poll_qr_auth_session(self, client_id, request_id=None, timeout=5):
        url = "https://api.steampowered.com/IAuthenticationService/PollAuthSessionStatus/v1/"
        response = requests.post(
            url,
            data={"client_id": client_id, "request_id": request_id or client_id},
            timeout=timeout,
        )
        return response
