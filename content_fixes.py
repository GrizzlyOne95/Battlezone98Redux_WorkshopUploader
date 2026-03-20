import os
import re


class ContentFixer:
    def __init__(self, logger=None):
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def build_upload_plan_prompt(self, item_id, game_name, appid, visibility, title, content, preview, auth_mode, manage_owner, change_note):
        mode = f"UPDATE ({item_id})" if item_id.isdigit() and item_id != "0" else "CREATE NEW"
        summary_lines = [
            "Upload Plan",
            f"- Mode: {mode}",
            f"- Game: {game_name} (AppID {appid})",
            f"- Workshop ID: {item_id or '0'}",
            f"- Visibility: {visibility}",
            f"- Title: {title}",
            f"- Content Folder: {os.path.abspath(content)}",
            f"- Preview Image: {os.path.abspath(preview)}",
            f"- Auth: {auth_mode}",
            f"- Manage Owner Field: {manage_owner or '(empty)'}",
            f"- Change Note: {change_note or '(empty)'}",
        ]
        return "\n".join(summary_lines) + "\n\nProceed with upload?"

    def apply_quick_fixes(self, issues):
        fixed_count = 0
        weapon_mask_re = re.compile(r'(weaponMask\s*=\s*)["\']?0+["\']?', re.IGNORECASE)
        missing_fields_re = re.compile(r'missing:\s*(.+)')

        for path, issue_type, detail, line_num in issues:
            try:
                if issue_type == "Crash Risk" and "weaponMask" in detail:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    if line_num <= len(lines):
                        lines[line_num - 1] = weapon_mask_re.sub(r'\1"00001"', lines[line_num - 1])
                        with open(path, "w", encoding="utf-8") as f:
                            f.writelines(lines)
                        fixed_count += 1
                elif issue_type == "Missing Fields":
                    match = missing_fields_re.search(detail)
                    if match:
                        keys = [key.strip() for key in match.group(1).split(",")]
                        with open(path, "a", encoding="utf-8") as f:
                            f.write("\n// Auto-fixed missing fields\n")
                            for key in keys:
                                f.write(f"{key} = 0\n")
                        fixed_count += 1
            except Exception as e:
                self.log(f"Quick Fix failed for {os.path.basename(path)}: {e}")
        return fixed_count

    def delete_legacy_files(self, files):
        count = 0
        for path in files:
            try:
                os.remove(path)
                count += 1
            except Exception as e:
                self.log(f"Error deleting {path}: {e}")
        return count

    def fix_trn_files(self, files):
        count = 0
        for path in files:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
                    content = f.read()
                content = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
                count += 1
            except Exception as e:
                self.log(f"Error fixing {path}: {e}")
        return count

    def fix_trn_duplicates(self, files):
        count = 0
        for path in files:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                new_lines = []
                size_found = False
                skip_mode = False

                for line in lines:
                    clean = line.split("//")[0].split("--")[0].strip().lower()
                    if clean == "[size]":
                        if size_found:
                            skip_mode = True
                        else:
                            size_found = True
                            skip_mode = False
                            new_lines.append(line)
                    elif clean.startswith("[") and clean.endswith("]"):
                        skip_mode = False
                        new_lines.append(line)
                    elif not skip_mode:
                        new_lines.append(line)

                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                count += 1
            except Exception as e:
                self.log(f"Error fixing {path}: {e}")
        return count
