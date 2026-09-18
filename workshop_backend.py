import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime


class WorkshopBackend:
    def __init__(self, steam_service, logger=None):
        self.steam_service = steam_service
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def build_steamcmd_command(self, exe, user, pwd, vdf, use_cached, guard_code=""):
        cmd = [exe, "+login"]
        if user:
            cmd.append(user)

        if not use_cached:
            if not user:
                raise ValueError("Username is required when cached credentials are disabled.")
            if pwd:
                cmd.append(pwd)
            if guard_code:
                cmd.append(guard_code)
        cmd.extend(["+workshop_build_item", vdf, "+quit"])
        return cmd

    def build_steamcmd_login_test_command(self, exe, user, pwd, use_cached, guard_code=""):
        cmd = [exe, "+login"]
        if user:
            cmd.append(user)

        if not use_cached:
            if not user:
                raise ValueError("Username is required when cached credentials are disabled.")
            if not pwd:
                raise ValueError("Password is required for a non-interactive login test.")
            cmd.append(pwd)
            if guard_code:
                cmd.append(guard_code)

        cmd.append("+quit")
        return cmd

    def launch_steamcmd(self, exe, user, pwd, vdf, use_cached, guard_code="", is_windows=False):
        cmd = self.build_steamcmd_command(exe, user, pwd, vdf, use_cached, guard_code=guard_code)
        creation_flags = subprocess.CREATE_NEW_CONSOLE if is_windows else 0
        process = subprocess.Popen(cmd, creationflags=creation_flags)
        return process, cmd

    def classify_steamcmd_login_output(self, output, returncode=None, timed_out=False):
        lower = (output or "").lower()

        bad_password_markers = (
            "invalid password",
            "invalid login",
            "login failure",
            "failed to login",
            "incorrect password",
        )
        guard_markers = (
            "steam guard code",
            "two-factor code",
            "two factor code",
            "two-factor authentication",
            "enter the current code",
            "account logon denied",
            "steam guard",
        )
        mobile_markers = (
            "steam mobile app",
            "mobile app to confirm",
            "approve the sign in",
            "approve this sign in",
            "waiting for confirmation",
            "confirm your sign in",
        )
        success_markers = (
            "logged in ok",
            "waiting for user info...ok",
            "login complete",
        )

        if any(marker in lower for marker in bad_password_markers):
            return "bad_credentials"
        if timed_out and any(marker in lower for marker in mobile_markers):
            return "timeout"
        if any(marker in lower for marker in mobile_markers):
            return "mobile_approval"
        if any(marker in lower for marker in guard_markers):
            return "guard_required"
        if any(marker in lower for marker in success_markers):
            return "verified"
        if returncode == 0 and not timed_out:
            return "verified"
        if timed_out:
            return "timeout"
        if returncode not in (None, 0):
            return "failed"
        return "checking"

    def test_steamcmd_login(
        self,
        exe,
        user,
        pwd,
        use_cached,
        guard_code="",
        timeout=180,
        state_callback=None,
    ):
        cmd = self.build_steamcmd_login_test_command(
            exe=exe,
            user=user,
            pwd=pwd,
            use_cached=use_cached,
            guard_code=guard_code,
        )
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="ignore",
            bufsize=1,
        )
        output_lines = []
        output_queue = queue.Queue()

        def reader():
            try:
                if process.stdout is None:
                    return
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break
                    output_queue.put(line)
            finally:
                output_queue.put(None)

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()
        deadline = time.monotonic() + max(1, timeout)
        last_state = "checking"
        if state_callback:
            state_callback(last_state)

        def drain_output():
            while True:
                try:
                    line = output_queue.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    break
                output_lines.append(line)

        timed_out = False
        while process.poll() is None:
            drain_output()
            current_output = "".join(output_lines)
            state = self.classify_steamcmd_login_output(current_output)
            if state != last_state and state in ("guard_required", "mobile_approval"):
                last_state = state
                if state_callback:
                    state_callback(state)

            if state == "guard_required" and not guard_code:
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                drain_output()
                return {
                    "returncode": process.returncode,
                    "success": False,
                    "state": "guard_required",
                    "output": "".join(output_lines),
                    "command": cmd,
                }

            if time.monotonic() >= deadline:
                timed_out = True
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                break
            time.sleep(0.1)

        drain_output()
        reader_thread.join(timeout=1)
        drain_output()
        output = "".join(output_lines)
        state = self.classify_steamcmd_login_output(
            output,
            returncode=process.returncode,
            timed_out=timed_out,
        )
        if guard_code and state == "guard_required":
            state = "failed"
        success = state == "verified"
        return {
            "returncode": process.returncode,
            "success": success,
            "state": state,
            "output": output,
            "command": cmd,
        }

    def query_workshop_items(self, api_key, identity_input, appid, resolve_steam_id):
        steam_id = resolve_steam_id(identity_input, api_key)
        if not steam_id:
            return None, [], {"pages": 0, "total": 0, "next_page": None}

        query_url = "https://api.steampowered.com/IPublishedFileService/GetUserFiles/v1/"
        page = 1
        page_count = 0
        total = 0
        items = []
        seen_ids = set()

        while page <= 1000:
            response = self.steam_service.request_with_retry(
                "GET",
                query_url,
                operation_name="Get user Workshop files",
                params={
                    "key": api_key,
                    "steamid": steam_id,
                    "appid": appid,
                    "page": page,
                    "numperpage": 100,
                },
                timeout=10,
            )
            payload = response.json().get("response", {})
            batch = payload.get("publishedfiledetails", []) or []
            page_count += 1

            try:
                total = int(payload.get("total", total or len(items)) or 0)
            except Exception:
                total = total or len(items)

            new_items = 0
            for item in batch:
                item_id = str(item.get("publishedfileid", "") or "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                items.append(item)
                new_items += 1

            if not batch or new_items == 0 or (total and len(items) >= total):
                break
            page += 1

        normalized = []
        vis_map = {0: "Public", 1: "Friends", 2: "Private"}
        for item in items:
            updated = item.get("time_updated")
            try:
                updated_label = datetime.fromtimestamp(int(updated)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                updated_label = "Unknown"
            try:
                visibility = int(item.get("visibility", -1))
            except Exception:
                visibility = -1
            normalized.append({
                "title": item.get("title", ""),
                "publishedfileid": item.get("publishedfileid", ""),
                "visibility_label": vis_map.get(visibility, "Unknown"),
                "updated_label": updated_label,
            })
        return steam_id, normalized, {
            "pages": page_count,
            "total": total or len(normalized),
            "next_page": page + 1 if total and len(normalized) < total else None,
        }

    def fetch_workshop_item_details(self, api_key, item_id):
        url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
        response = self.steam_service.request_with_retry(
            "POST",
            url,
            operation_name="Fetch Workshop item details",
            data={"key": api_key, "itemcount": 1, "publishedfileids[0]": item_id},
            timeout=10,
        )
        details = response.json().get("response", {}).get("publishedfiledetails", [{}])[0]
        return details or {}

    def download_preview_bytes(self, preview_url):
        if not preview_url:
            return b""
        response = self.steam_service.request_with_retry(
            "GET",
            preview_url,
            operation_name="Download Workshop preview",
            stream=True,
            timeout=10,
        )
        if response.ok:
            return response.content
        return b""

    def update_workshop_tags(
        self,
        api_key,
        item_id,
        appid,
        tags,
        change_note="",
        steamworks_updater=None,
        base_dir=None,
        create_appid_file=False,
    ):
        native_error = None
        if steamworks_updater is not None:
            try:
                return steamworks_updater.try_update_tags(
                    appid=appid,
                    publishedfileid=item_id,
                    tags=tags,
                    change_note=change_note,
                    base_dir=base_dir,
                    create_appid_file=create_appid_file,
                )
            except Exception as e:
                native_error = e

        if not api_key:
            if native_error:
                raise native_error
            raise ValueError("API key is required for Web API tag updates.")

        url = "https://api.steampowered.com/IPublishedFileService/Update/v1/"
        data = {
            "key": api_key,
            "publishedfileid": item_id,
            "appid": appid,
        }
        for i, tag in enumerate(tags):
            data[f"tags[{i}]"] = tag

        self.steam_service.request_with_retry(
            "POST",
            url,
            operation_name="Update Workshop tags",
            data=data,
            timeout=10,
        )
        return {
            "method": "web_api",
            "native_error": str(native_error) if native_error else "",
        }

    def get_log_paths(self, steamcmd_exe, appid):
        base_dir = os.path.dirname(steamcmd_exe)
        return [
            ("Build Log", os.path.join(base_dir, "workshopbuilds", f"depot_build_{appid}.log")),
            ("Transfer Log", os.path.join(base_dir, "logs", "Workshop_log.txt")),
        ]

    def analyze_last_upload_log(self, steamcmd_exe, appid):
        build_log = self.get_log_paths(steamcmd_exe, appid)[0][1]
        if not os.path.exists(build_log):
            return None

        try:
            with open(build_log, "r", errors="ignore") as f:
                lines = f.readlines()
            errors = [line.strip() for line in lines if "error" in line.lower() or "failed" in line.lower()]
            if errors:
                return "\n".join(errors[-5:])
        except Exception:
            pass
        return None
