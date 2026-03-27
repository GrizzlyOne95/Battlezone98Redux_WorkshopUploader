import hashlib
import os
import re
from datetime import datetime, timezone


class ProjectStore:
    def __init__(self, profiles_dir, file_manager):
        self.profiles_dir = profiles_dir
        self.file_manager = file_manager

    def _slugify(self, value):
        text = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
        return text or "project"

    def _profile_path_for_mod(self, mod_path):
        normalized = os.path.abspath(mod_path or "").lower()
        digest = hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:10]
        label = self._slugify(os.path.basename(normalized) or "project")
        return os.path.join(self.profiles_dir, f"{label}-{digest}.json")

    def _iter_profile_paths(self):
        if not os.path.isdir(self.profiles_dir):
            return []
        names = [
            os.path.join(self.profiles_dir, name)
            for name in os.listdir(self.profiles_dir)
            if name.lower().endswith(".json")
        ]
        return sorted(names)

    def list_projects(self):
        projects = []
        for path in self._iter_profile_paths():
            try:
                data = self.file_manager.load_profile(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            data["profile_path"] = path
            projects.append(data)
        projects.sort(key=lambda item: item.get("last_opened", ""), reverse=True)
        return projects

    def load_project(self, profile_path):
        data = self.file_manager.load_profile(profile_path)
        data["profile_path"] = profile_path
        return data

    def find_by_mod_path(self, mod_path):
        if not mod_path:
            return None

        canonical = os.path.abspath(mod_path)
        preferred_path = self._profile_path_for_mod(canonical)
        if os.path.exists(preferred_path):
            return self.load_project(preferred_path)

        for entry in self.list_projects():
            stored_path = entry.get("mod_path", "")
            if stored_path and os.path.abspath(stored_path) == canonical:
                return entry
        return None

    def save_project(self, data):
        payload = dict(data or {})
        mod_path = payload.get("mod_path", "")
        profile_path = payload.get("profile_path") or self._profile_path_for_mod(mod_path or payload.get("title", "project"))
        payload["profile_path"] = profile_path
        payload["last_opened"] = datetime.now(timezone.utc).isoformat()
        self.file_manager.save_profile(profile_path, payload)
        return profile_path
