import configparser
import hashlib
import os
import re


class ModScanner:
    def __init__(self, resource_dir, logger=None):
        self.resource_dir = resource_dir
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def _load_odf_rules(self):
        allowed_headers = set()
        allowed_params = {}
        required_params = {}

        header_list_path = os.path.join(self.resource_dir, "odfHeaderList.txt")
        if os.path.exists(header_list_path):
            with open(header_list_path, "r", encoding="utf-8", errors="ignore") as f:
                allowed_headers = {line.strip().lower() for line in f if line.strip()}

        params_list_path = os.path.join(self.resource_dir, "bzrODFparams.txt")
        if os.path.exists(params_list_path):
            current_class = None
            with open(params_list_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("-") or line.startswith("//"):
                        continue

                    if line.startswith("[") and line.endswith("]"):
                        current_class = line[1:-1].strip()
                        if re.match(r"^[A-Za-z0-9_]+$", current_class):
                            current_class = current_class.lower()
                            allowed_params[current_class] = set()
                            required_params[current_class] = set()
                        else:
                            current_class = None
                        continue

                    if not current_class:
                        continue

                    token = line.split()[0]
                    is_required = token.startswith("!")
                    param = token.lstrip("!").rstrip("?").strip().lower()
                    if not param:
                        continue

                    allowed_params[current_class].add(param)
                    if is_required:
                        required_params[current_class].add(param)

        return allowed_headers, allowed_params, required_params

    def build_inventory(self, mod_dir):
        inventory = []
        for root, _, files in os.walk(mod_dir):
            for name in files:
                path = os.path.join(root, name)
                stat = os.stat(path)
                inventory.append({
                    "name": name,
                    "name_lower": name.lower(),
                    "path": path,
                    "rel_path": os.path.relpath(path, mod_dir).replace("\\", "/").lower(),
                    "size": stat.st_size,
                    "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
                })
        return inventory

    def fingerprint_inventory(self, inventory):
        digest = hashlib.sha1()
        for entry in sorted(inventory, key=lambda item: item["rel_path"]):
            digest.update(entry["rel_path"].encode("utf-8", errors="ignore"))
            digest.update(str(entry["mtime_ns"]).encode("ascii", errors="ignore"))
            digest.update(str(entry["size"]).encode("ascii", errors="ignore"))
        return digest.hexdigest()

    def collect_findings(self, mod_dir, inventory=None):
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        issues = self.scan_mod_safety(mod_dir, inventory=inventory)
        issues.extend(self.scan_asset_references(mod_dir, inventory=inventory))
        validation_errors, validation_warnings = self.validate_content_structure(mod_dir)
        trn_line_endings, trn_duplicate_headers = self.scan_trn_safety(mod_dir, inventory=inventory)
        legacy_files = self.scan_legacy_files(mod_dir, inventory=inventory)
        return {
            "inventory": inventory,
            "issues": issues,
            "validation_errors": validation_errors,
            "validation_warnings": validation_warnings,
            "trn_line_endings": trn_line_endings,
            "trn_duplicate_headers": trn_duplicate_headers,
            "legacy_files": legacy_files,
        }

    def scan_mod_safety(self, mod_dir, inventory=None):
        allowed_headers, allowed_params, required_params = self._load_odf_rules()

        if not allowed_headers:
            return []

        issues = []
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        for entry in inventory:
            if not entry["name_lower"].endswith(".odf"):
                continue
            path = entry["path"]
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    current_header = None
                    current_header_key = None
                    current_header_line = 0
                    found_params = set()

                    for i, line in enumerate(f):
                        line = line.split("//")[0].split("--")[0].strip()
                        if not line:
                            continue
                        if line.startswith("//") or line.startswith("--"):
                            continue

                        if line.startswith("[") and line.endswith("]"):
                            if current_header_key and current_header_key in required_params:
                                missing = required_params[current_header_key] - found_params
                                if missing:
                                    issues.append((path, "Missing Fields", f"[{current_header}] missing: {', '.join(sorted(missing))}", current_header_line))

                            header = line[1:-1]
                            header_key = header.lower()
                            current_header = header
                            current_header_key = header_key
                            current_header_line = i + 1
                            found_params = set()

                            if header_key not in allowed_headers:
                                issues.append((path, "Invalid Header", header, i + 1))

                        elif "=" in line and current_header:
                            key = line.split("=", 1)[0].strip()
                            key_key = key.lower()
                            if current_header_key in allowed_params:
                                if key_key not in allowed_params[current_header_key]:
                                    issues.append((path, "Unknown Field", f"[{current_header}] {key}", i + 1))
                                else:
                                    found_params.add(key_key)

                    if current_header_key and current_header_key in required_params:
                        missing = required_params[current_header_key] - found_params
                        if missing:
                            issues.append((path, "Missing Fields", f"[{current_header}] missing: {', '.join(sorted(missing))}", current_header_line))

            except Exception as e:
                self.log(f"Warning: Could not scan {entry['name']}: {e}")
        return issues

    def scan_asset_references(self, mod_dir, inventory=None):
        issues = []
        existing_files = set()
        files_to_process = []

        odf_pattern = re.compile(r'(geometryName|cockpitName|turretName)\s*=\s*"([^"]+)"', re.IGNORECASE)
        material_pattern = re.compile(r'texture\s+([^\s]+)', re.IGNORECASE)

        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        for entry in inventory:
            name_lower = entry["name_lower"]
            existing_files.add(name_lower)
            if name_lower.endswith(".odf") or name_lower.endswith(".material"):
                files_to_process.append(entry)

        for entry in files_to_process:
            is_odf = entry["name_lower"].endswith(".odf")
            path = entry["path"]
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        if "//" in line:
                            line = line.split("//")[0]
                        line = line.strip()
                        if not line:
                            continue

                        if is_odf:
                            match = odf_pattern.search(line)
                            if match:
                                asset = match.group(2).lower()
                                if asset and asset not in existing_files:
                                    issues.append((path, "Missing Asset", f"Missing {match.group(1)}: {asset}", i + 1))
                        else:
                            match = material_pattern.search(line)
                            if match:
                                asset = match.group(1).lower()
                                if asset and asset not in existing_files:
                                    issues.append((path, "Missing Asset", f"Missing texture: {asset}", i + 1))
            except Exception:
                pass
        return issues

    def scan_trn_safety(self, mod_dir, inventory=None):
        le_issues = []
        dup_issues = []
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        for entry in inventory:
            if not entry["name_lower"].endswith(".trn"):
                continue
            path = entry["path"]
            try:
                with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
                    text = f.read()

                if re.search(r"(?<!\r)\n", text) or re.search(r"\r(?!\n)", text):
                    le_issues.append(path)

                if len(re.findall(r"^\s*\[Size\]", text, re.MULTILINE | re.IGNORECASE)) > 1:
                    dup_issues.append(path)

            except Exception as e:
                self.log(f"Warning: Could not scan TRN {entry['name']}: {e}")
        return le_issues, dup_issues

    def scan_legacy_files(self, mod_dir, inventory=None):
        legacy_files = []
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        for entry in inventory:
            if entry["name_lower"].endswith(".map"):
                legacy_files.append(entry["path"])
        return legacy_files

    def validate_content_structure(self, mod_dir):
        errors = []
        warnings = []

        try:
            files = os.listdir(mod_dir)
        except Exception as e:
            errors.append(f"Could not access content folder: {e}")
            return errors, warnings

        for name in files[:]:
            if name.lower() == "desktop.ini":
                try:
                    os.remove(os.path.join(mod_dir, name))
                    self.log(f"Removed hidden system file: {name}")
                    files.remove(name)
                except Exception as e:
                    self.log(f"Warning: Could not remove {name}: {e}")

        ini_files = [name for name in files if name.lower().endswith(".ini") and os.path.isfile(os.path.join(mod_dir, name))]

        if not ini_files:
            errors.append("Missing configuration (.ini) file in content root.")
            return errors, warnings

        target_ini = ini_files[0]
        ini_path = os.path.join(mod_dir, target_ini)

        config = configparser.ConfigParser()
        try:
            with open(ini_path, "r", encoding="utf-8-sig") as f:
                config.read_file(f)
        except Exception:
            try:
                config.read(ini_path)
            except Exception as e:
                errors.append(f"Failed to parse {target_ini}: {e}")
                return errors, warnings

        if "WORKSHOP" not in config:
            errors.append(f"{target_ini} missing [WORKSHOP] section.")
            return errors, warnings

        map_type = config["WORKSHOP"].get("maptype", "").lower().strip().strip('"').strip("'")
        valid_types = ["instant_action", "multiplayer", "mod"]

        if map_type not in valid_types:
            errors.append(f"Invalid mapType '{map_type}' in {target_ini}.\nMust be one of: {', '.join(valid_types)}")
            return errors, warnings

        base_name = os.path.splitext(target_ini)[0]
        files_lower = set(name.lower() for name in files)

        def check_ext(ext, required=True):
            if f"{base_name}{ext}".lower() not in files_lower:
                kind = "essential" if required else "optional"
                (errors if required else warnings).append(f"Missing {kind} file: {base_name}{ext}")

        if map_type in ["multiplayer", "instant_action"]:
            for ext in [".hg2", ".trn", ".mat", ".bzn", ".lgt"]:
                check_ext(ext)

            if map_type == "multiplayer":
                for ext in [".bmp", ".des", ".vxt"]:
                    check_ext(ext, required=False)
                if "MULTIPLAYER" not in config:
                    errors.append(f"{target_ini} missing [MULTIPLAYER] section.")
                else:
                    for key in ["minplayers", "maxplayers", "gametype"]:
                        if key not in config["MULTIPLAYER"]:
                            warnings.append(f"[MULTIPLAYER] missing '{key}'")

        return errors, warnings
