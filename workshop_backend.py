import os
import subprocess
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

    def launch_steamcmd(self, exe, user, pwd, vdf, use_cached, guard_code="", is_windows=False):
        cmd = self.build_steamcmd_command(exe, user, pwd, vdf, use_cached, guard_code=guard_code)
        creation_flags = subprocess.CREATE_NEW_CONSOLE if is_windows else 0
        process = subprocess.Popen(cmd, creationflags=creation_flags)
        return process, cmd

    def query_workshop_items(self, api_key, identity_input, appid, resolve_steam_id):
        steam_id = resolve_steam_id(identity_input, api_key)
        if not steam_id:
            return None, []

        query_url = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
        params = {
            "key": api_key,
            "creator_appid": appid,
            "appid": appid,
            "numperpage": 100,
            "return_metadata": 1,
            "steamid": steam_id,
        }
        response = self.steam_service.request_with_retry(
            "GET",
            query_url,
            operation_name="Query Workshop files",
            params=params,
            timeout=10,
        )
        items = response.json().get("response", {}).get("publishedfiledetails", [])
        normalized = []
        vis_map = {0: "Public", 1: "Friends", 2: "Private"}
        for item in items:
            normalized.append({
                "title": item.get("title", ""),
                "publishedfileid": item.get("publishedfileid", ""),
                "visibility_label": vis_map.get(item.get("visibility"), "Unknown"),
                "updated_label": datetime.fromtimestamp(item["time_updated"]).strftime("%Y-%m-%d %H:%M"),
            })
        return steam_id, normalized

    def fetch_workshop_item_details(self, api_key, item_id):
        url = "https://api.steampowered.com/IPublishedFileService/GetPublishedFileDetails/v1/"
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
