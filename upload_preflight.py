import os


class UploadPreflight:
    def __init__(self, logger=None):
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def validate_inputs(
        self,
        title,
        description,
        steamcmd_path,
        content_path,
        preview_path,
        username,
        use_cached_creds,
        title_limit,
        description_limit,
    ):
        if len(title) > title_limit:
            return ("Title Too Long", f"Your title is {len(title)} characters long. The maximum is {title_limit}.")
        if not title:
            return ("Missing Title", "The workshop item must have a title.")
        if len(description) > description_limit:
            return (
                "Description Too Long",
                f"Your description is {len(description)} characters long. The maximum is {description_limit}.",
            )
        if not all([steamcmd_path, content_path, preview_path]):
            return ("Error", "Missing required fields (SteamCMD, Content Folder, Preview Image).")
        if not use_cached_creds and not username.strip():
            return ("Error", "Steam Username is required unless 'USE CACHED CREDENTIALS' is enabled.")
        if not os.path.exists(steamcmd_path):
            return ("Error", "SteamCMD executable not found.")
        return None

    def build_safety_rows(self, issues, mod_dir):
        rows = []
        for path, issue_type, detail, line in issues:
            try:
                display_path = os.path.relpath(path, mod_dir)
            except Exception:
                display_path = path
            rows.append({
                "display_path": display_path,
                "full_path": path,
                "issue_type": issue_type,
                "detail": detail,
                "line": line,
            })
        return rows

    def write_upload_vdf(
        self,
        base_dir,
        appid,
        publishedfileid,
        contentfolder,
        previewfile,
        visibility,
        title,
        description,
        changenote,
        build_upload_vdf_content,
    ):
        vdf_path = os.path.join(base_dir, "upload.vdf")
        vdf_content = build_upload_vdf_content(
            appid=appid,
            publishedfileid=publishedfileid,
            contentfolder=contentfolder,
            previewfile=previewfile,
            visibility=visibility,
            title=title,
            description=description,
            changenote=changenote,
        )
        with open(vdf_path, "w", encoding="utf-8") as f:
            f.write(vdf_content)
        return vdf_path
