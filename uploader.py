import os
import sys
import subprocess
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ctypes
import re
import requests
from datetime import datetime, timezone
from mod_scanner import ModScanner
from steam_service import SteamService
from workshop_backend import WorkshopBackend
from memory_analyzer import MemoryAnalyzer
from content_fixes import ContentFixer
from app_file_manager import AppFileManager
from project_store import ProjectStore
from upload_preflight import UploadPreflight
from steamworks_tags import SteamworksTagUpdater

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    qrcode = None
    HAS_QRCODE = False

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    keyring = None
    HAS_KEYRING = False

# Platform check
IS_WINDOWS = sys.platform == "win32"

# --- CONFIGURATION ---
CONFIG_FILE_NAME = "uploader_config.json"
STEAM_TITLE_LIMIT = 128
STEAM_DESC_LIMIT = 8000
REQUEST_RETRY_ATTEMPTS = 3
REQUEST_BACKOFF_SECONDS = 1.0
KEYRING_SERVICE = "BattlezoneWorkshopUploader"
KEYRING_API_KEY_ACCOUNT = "steam_web_api_key"

class ToolTip:
    def __init__(self, widget, text, bg="#1a1a1a", fg="#00ffff"):
        self.widget = widget
        self.text = text
        self.bg = bg
        self.fg = fg
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left',
                       background=self.bg, foreground=self.fg, 
                       relief='solid', borderwidth=1, font=("Consolas", "9"))
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class TemplateWizard(tk.Toplevel):
    def __init__(self, parent, colors, on_success):
        super().__init__(parent)
        self.title("New Project Wizard")
        self.geometry("500x550")
        self.configure(bg=colors["bg"])
        self.colors = colors
        self.on_success = on_success
        self.resizable(False, False)
        
        # Variables
        self.name_var = tk.StringVar(value="my_new_map")
        self.type_var = tk.StringVar(value="multiplayer")
        self.min_p_var = tk.StringVar(value="2")
        self.max_p_var = tk.StringVar(value="4")
        self.game_type_var = tk.StringVar(value="S")
        
        self.setup_ui()
        self.transient(parent)
        self.grab_set()

    def setup_ui(self):
        style = ttk.Style()
        c = self.colors
        
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        
        ttk.Label(frame, text="CREATE NEW BZR PROJECT", font=("Consolas", 14, "bold"), foreground=c["highlight"]).pack(pady=(0, 20))
        
        # Name
        ttk.Label(frame, text="Mission Name:").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.name_var).pack(fill="x", pady=(0, 15))
        
        # Map Type
        ttk.Label(frame, text="Map Type:").pack(anchor="w")
        type_combo = ttk.Combobox(frame, textvariable=self.type_var, values=["instant_action", "multiplayer", "mod"], state="readonly")
        type_combo.pack(fill="x", pady=(0, 15))
        type_combo.bind("<<ComboboxSelected>>", self._toggle_mp_fields)
        
        # MP Specifics
        self.mp_frame = ttk.LabelFrame(frame, text=" MULTIPLAYER SETTINGS ", padding=10)
        self.mp_frame.pack(fill="x", pady=5)
        
        ttk.Label(self.mp_frame, text="Game Type:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(self.mp_frame, textvariable=self.game_type_var, values=["D (Deathmatch)", "S (Strategy)", "K (King Of The Hill)", "M (Multiplayer Instant)", "A (Multiplayer Action)"], state="readonly", width=25).grid(row=0, column=1, sticky="ew", padx=5)
        
        ttk.Label(self.mp_frame, text="Min Players:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(self.mp_frame, textvariable=self.min_p_var, width=5).grid(row=1, column=1, sticky="w", padx=5, pady=5)
        
        ttk.Label(self.mp_frame, text="Max Players:").grid(row=2, column=0, sticky="w")
        ttk.Entry(self.mp_frame, textvariable=self.max_p_var, width=5).grid(row=2, column=1, sticky="w", padx=5)
        
        # Actions
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", side="bottom", pady=20)
        
        ttk.Button(btn_frame, text="CREATE PROJECT", command=self.create_project, style="Success.TButton").pack(side="right", padx=5)
        ttk.Button(btn_frame, text="CANCEL", command=self.destroy).pack(side="right")

    def _toggle_mp_fields(self, event=None):
        if self.type_var.get() == "multiplayer":
            self.mp_frame.pack(fill="x", pady=5, after=self.mp_frame.master.children.get("type_combo")) # Helper logic
            # Actually just simple pack/unpack
            self.mp_frame.pack(fill="x", pady=5)
        else:
            self.mp_frame.pack_forget()

    def create_project(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Error", "Project name cannot be empty.")
            return
            
        target_dir = filedialog.askdirectory(title="Select Parent Folder for New Project")
        if not target_dir: return
        
        project_path = os.path.join(target_dir, name)
        if os.path.exists(project_path):
            if not messagebox.askyesno("Warning", f"Folder '{name}' already exists. Overwrite?"):
                return
        
        try:
            os.makedirs(project_path, exist_ok=True)
            
            # 1. Create .INI file
            m_type = self.type_var.get()
            g_type = self.game_type_var.get()[0]
            
            ini_content = f"""[DESCRIPTION]
missionName = "{name}"

[WORKSHOP]
mapType = "{m_type}"
;customtags = ""

"""
            if m_type == "multiplayer":
                ini_content += f"""[MULTIPLAYER]
minPlayers = "{self.min_p_var.get()}"
maxPlayers = "{self.max_p_var.get()}"
gameType = "{g_type}"
; D=Deathmatch, S=Strategy, K=KOTH, M=MP Instant, A=MP Action
"""
            
            with open(os.path.join(project_path, f"{name}.ini"), "w", encoding="utf-8") as f:
                f.write(ini_content)
                
            # 2. Create placeholder map files
            exts = [".hg2", ".trn", ".mat", ".bzn", ".lgt"]
            if m_type == "multiplayer":
                exts.extend([".bmp", ".des", ".vxt"])
                
            for ext in exts:
                with open(os.path.join(project_path, f"{name}{ext}"), "w", encoding="utf-8") as f:
                    if ext == ".trn":
                        f.write("[Size]\nTileSize = 8\nSizeX = 128\nSizeZ = 128\n")
                    elif ext == ".des":
                        f.write(f"Description for {name}")
                    else:
                        f.write("") # Just touch the file
            
            self.on_success(project_path)
            self.destroy()
            messagebox.showinfo("Success", f"Project '{name}' created successfully!")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create project: {e}")

class WorkshopUploader:
    def __init__(self, root):
        self.root = root
        self.root.title("Battlezone Workshop Uploader")
        self.root.geometry("1360x900")
        
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
            self.resource_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            self.resource_dir = self.base_dir
        self.config_path = os.path.join(self.base_dir, CONFIG_FILE_NAME)
            
        self.profiles_dir = os.path.join(self.base_dir, "profiles")
        os.makedirs(self.profiles_dir, exist_ok=True)
            
        self.temp_dir = os.path.join(self.base_dir, "temp_previews")
        os.makedirs(self.temp_dir, exist_ok=True)

        self.steamcmd_process = None
        self.file_manager = AppFileManager(logger=self.log, has_pil=HAS_PIL, image_module=Image if HAS_PIL else None)
        self.project_store = ProjectStore(self.profiles_dir, self.file_manager)
        self.upload_preflight = UploadPreflight(logger=self.log)
        self.steamworks_tag_updater = SteamworksTagUpdater(logger=self.log)

        # --- THEME & COLORS (Matched to cmd.py) ---
        self.colors = {
            "bg": "#0a0a0a", "fg": "#d4d4d4",
            "highlight": "#00ff00", "dark_highlight": "#004400", "accent": "#00ffff"
        }
        
        self.games = {
            "BZ98R": {"name": "Battlezone 98 Redux", "appid": "301650"}
        }

        self.load_custom_fonts()
        self.config = self.load_config()
        
        # Variables
        self.steamcmd_path = tk.StringVar(value=self.config.get("steamcmd_path", ""))
        self.api_key_var = tk.StringVar(value="")
        
        last_game = self.config.get("last_game", "BZ98R")
        if last_game not in self.games: last_game = "BZ98R"
        self.game_var = tk.StringVar(value=last_game)
        
        self.mod_path = tk.StringVar()
        self.mod_path.trace_add("write", self._on_mod_path_changed)
        self.preview_path = tk.StringVar()
        self.title_var = tk.StringVar()
        self.title_var.trace_add("write", self._update_title_counter)
        self.note_var = tk.StringVar(value="Initial Release")
        self.tags_var = tk.StringVar()
        self.visibility_var = tk.StringVar(value="0 (Public)")
        self.item_id_var = tk.StringVar(value="0")
        self.item_id_var.trace_add("write", self._update_upload_mode_indicator)
        
        self.username_var = tk.StringVar(value=self.config.get("username", ""))
        self.manage_identity_var = tk.StringVar(value=self.config.get("manage_identity", ""))
        self.password_var = tk.StringVar()
        self.steam_guard_var = tk.StringVar()
        self.use_cached_creds_var = tk.BooleanVar(value=self.config.get("use_cached_creds", False))
        self.use_cached_creds_var.trace_add("write", self._toggle_auth_fields)
        self.experimental_native_appid_var = tk.BooleanVar(value=self.config.get("experimental_native_appid", False))
        self.busy_status_var = tk.StringVar(value="STATUS: IDLE")
        self._active_operations = set()
        self._busy_lock = threading.Lock()
        self._warned_no_keyring = False
        self.current_project_profile_path = ""
        self.current_inventory = []
        self.current_findings = None
        self.current_readiness = None
        self.current_project_data = {}
        self.current_project_signature = None
        self.pending_publish_signature = None
        self.pending_publish_inventory = None

        self.qr_session_id = None
        self.qr_poll_timer = None
        
        self.watch_mode_var = tk.BooleanVar(value=False)
        self.watch_thread = None
        self.last_watch_signature = None
        self.last_watch_summary = None
        self.mod_scanner = ModScanner(self.resource_dir, logger=self.log)
        self.steam_service = SteamService(logger=self.log)
        self.workshop_backend = WorkshopBackend(self.steam_service, logger=self.log)
        self.memory_analyzer = MemoryAnalyzer(logger=self.log, has_pil=HAS_PIL, image_module=Image if HAS_PIL else None)
        self.content_fixer = ContentFixer(logger=self.log)
        self.project_name_var = tk.StringVar(value="NO PROJECT")
        self.project_hint_var = tk.StringVar(value="Select a mod folder to begin.")
        self.publish_target_var = tk.StringVar(value="TARGET: CREATE NEW ITEM")
        self.last_upload_var = tk.StringVar(value="LAST PUBLISH: NONE")
        self.changed_since_upload_var = tk.StringVar(value="CHANGED FILES: UNKNOWN")
        self.readiness_summary_var = tk.StringVar(value="Readiness: Select a content folder.")
        self.readiness_detail_var = tk.StringVar(value="")
        self.library_status_var = tk.StringVar(value="Workshop library not loaded.")
        self.project_filter_var = tk.StringVar()
        
        self.setup_styles()
        self.setup_ui()
        self.refresh_recent_projects()

        # Load API key from secure storage; migrate legacy config value if present.
        self._load_api_key_from_secure_store()
        legacy_api_key = self.config.get("api_key", "")
        if not self.api_key_var.get() and legacy_api_key:
            self.api_key_var.set(legacy_api_key)
            self._save_api_key_to_secure_store()

        # Initial toggle state
        self._toggle_auth_fields()

        # Apply theme
        self.root.configure(bg=self.colors["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_custom_fonts(self):
        self.current_font = "Consolas"
        if IS_WINDOWS:
            # Try to load BZONE.ttf if available (assuming it might be in resource dir like cmd.py)
            font_path = os.path.join(self.resource_dir, "BZONE.ttf")
            if os.path.exists(font_path):
                try:
                    if ctypes.windll.gdi32.AddFontResourceExW(font_path, 0x10, 0) > 0:
                        self.current_font = "BZONE"
                except Exception: pass

    def load_config(self):
        candidate_paths = [self.config_path]
        legacy_path = os.path.abspath(CONFIG_FILE_NAME)
        if legacy_path not in candidate_paths:
            candidate_paths.append(legacy_path)
        return self._get_file_manager().load_config(self.config_path, legacy_paths=candidate_paths[1:])

    def save_config(self):
        cfg = {
            "steamcmd_path": self.steamcmd_path.get(),
            "last_game": self.game_var.get(),
            "username": self.username_var.get(),
            "manage_identity": self.manage_identity_var.get(),
            "use_cached_creds": self.use_cached_creds_var.get(),
            "experimental_native_appid": self.experimental_native_appid_var.get(),
        }
        try:
            self._get_file_manager().save_config(self.config_path, cfg)
        except Exception:
            pass
        self._save_api_key_to_secure_store()

    def _get_desc_text_value(self):
        if hasattr(self, "desc_text"):
            try:
                return self.desc_text.get("1.0", "end-1c")
            except Exception:
                return ""
        return ""

    def _set_desc_text_value(self, value):
        if not hasattr(self, "desc_text"):
            return
        try:
            self.desc_text.delete("1.0", "end")
            self.desc_text.insert("1.0", value or "")
        except Exception:
            return
        self._update_desc_counter()

    def _normalize_visibility_value(self, value):
        text = str(value or "").strip()
        if not text:
            return "0 (Public)"
        if text in ("0", "1", "2"):
            labels = {"0": "Public", "1": "Friends", "2": "Private"}
            return f"{text} ({labels[text]})"
        return text

    def _visibility_code(self):
        text = self._normalize_visibility_value(self.visibility_var.get())
        return text.split()[0]

    def _build_inventory_snapshot(self, inventory):
        snapshot = {}
        for entry in inventory or []:
            snapshot[entry["rel_path"]] = {
                "size": entry["size"],
                "mtime_ns": entry["mtime_ns"],
            }
        return snapshot

    def _count_changed_files(self, inventory, last_snapshot):
        current = self._build_inventory_snapshot(inventory)
        previous = last_snapshot or {}
        changed = 0
        keys = set(current) | set(previous)
        for key in keys:
            if current.get(key) != previous.get(key):
                changed += 1
        return changed

    def _build_project_payload(self):
        name = os.path.basename(self.mod_path.get().rstrip("\\/")) if self.mod_path.get() else "project"
        payload = {
            "project_name": name,
            "mod_path": self.mod_path.get(),
            "preview_path": self.preview_path.get(),
            "title": self.title_var.get(),
            "description": self._get_desc_text_value(),
            "visibility": self._normalize_visibility_value(self.visibility_var.get()),
            "item_id": self.item_id_var.get(),
            "change_note": self.note_var.get(),
            "tags": self.tags_var.get(),
            "manage_identity": self.manage_identity_var.get(),
        }
        if self.current_project_profile_path:
            payload["profile_path"] = self.current_project_profile_path
        if self.current_project_data.get("last_upload_signature"):
            payload["last_upload_signature"] = self.current_project_data.get("last_upload_signature")
        if self.current_project_data.get("last_upload_inventory"):
            payload["last_upload_inventory"] = self.current_project_data.get("last_upload_inventory")
        if self.current_project_data.get("last_upload_at"):
            payload["last_upload_at"] = self.current_project_data.get("last_upload_at")
        if self.current_project_data.get("last_uploaded_item_id"):
            payload["last_uploaded_item_id"] = self.current_project_data.get("last_uploaded_item_id")
        return payload

    def save_current_project_state(self, quiet=False):
        mod_path = self.mod_path.get().strip()
        if not mod_path:
            if not quiet:
                messagebox.showinfo("Project", "Select a content folder before saving project state.")
            return None

        payload = self._build_project_payload()
        try:
            profile_path = self.project_store.save_project(payload)
        except Exception as e:
            if not quiet:
                messagebox.showerror("Error", f"Failed to save project state: {e}")
            return None

        self.current_project_profile_path = profile_path
        self.current_project_data = dict(payload, profile_path=profile_path)
        self.project_name_var.set(payload["project_name"].upper())
        self.project_hint_var.set(os.path.abspath(mod_path))
        self.refresh_recent_projects()
        if not quiet:
            self.log(f"Saved project state: {os.path.basename(profile_path)}")
        return profile_path

    def refresh_recent_projects(self):
        if not hasattr(self, "project_tree"):
            return

        filter_text = self.project_filter_var.get().strip().lower()
        self.project_tree.delete(*self.project_tree.get_children())
        for project in self.project_store.list_projects():
            project_name = project.get("project_name") or os.path.basename(project.get("mod_path", "")) or "(unnamed)"
            search_blob = " ".join([
                project_name,
                project.get("title", ""),
                project.get("mod_path", ""),
                project.get("item_id", ""),
            ]).lower()
            if filter_text and filter_text not in search_blob:
                continue
            updated = project.get("last_opened", "")
            if "T" in updated:
                updated = updated.split("T", 1)[0]
            item_id = project.get("item_id", "0") or "0"
            self.project_tree.insert("", "end", values=(project_name, item_id, updated), tags=(project.get("profile_path", ""),))

    def _load_project_from_path(self, profile_path):
        data = self.project_store.load_project(profile_path)
        self.current_project_profile_path = profile_path
        self.current_project_data = data
        self.mod_path.set(data.get("mod_path", ""))
        self.preview_path.set(data.get("preview_path", ""))
        self.title_var.set(data.get("title", ""))
        self._set_desc_text_value(data.get("description", ""))
        self.visibility_var.set(self._normalize_visibility_value(data.get("visibility", "0 (Public)")))
        self.item_id_var.set(data.get("item_id", "0"))
        self.note_var.set(data.get("change_note", ""))
        self.tags_var.set(data.get("tags", ""))
        self.manage_identity_var.set(data.get("manage_identity", self.manage_identity_var.get()))
        self.project_name_var.set((data.get("project_name") or os.path.basename(data.get("mod_path", "")) or "NO PROJECT").upper())
        mod_path = data.get("mod_path", "")
        self.project_hint_var.set(os.path.abspath(mod_path) if mod_path else "Saved project loaded.")
        self._update_project_status(self.current_inventory)
        self.refresh_recent_projects()
        return data

    def open_selected_project(self):
        if not hasattr(self, "project_tree"):
            return False
        selected = self.project_tree.selection()
        if not selected:
            messagebox.showinfo("Project", "Select a saved project first.")
            return False

        tags = self.project_tree.item(selected[0]).get("tags", [])
        if not tags:
            return False
        self._load_project_from_path(tags[0])
        self.refresh_current_project_readiness()
        self.log(f"Loaded project: {os.path.basename(tags[0])}")
        return True

    def _handle_new_project_created(self, project_path):
        self.mod_path.set(project_path)
        self.refresh_current_project_readiness()
        self.save_current_project_state(quiet=True)

    def _on_mod_path_changed(self, *args):
        mod_path = self.mod_path.get().strip()
        if not hasattr(self, "project_name_var"):
            return
        if not mod_path:
            self.project_name_var.set("NO PROJECT")
            self.project_hint_var.set("Select a mod folder to begin.")
            return

        matched = self.project_store.find_by_mod_path(mod_path)
        if matched and matched.get("profile_path") != self.current_project_profile_path:
            self._load_project_from_path(matched["profile_path"])
            return

        project_name = os.path.basename(mod_path.rstrip("\\/")) or "project"
        self.project_name_var.set(project_name.upper())
        self.project_hint_var.set(os.path.abspath(mod_path))
        self.current_project_profile_path = self.current_project_profile_path or self.project_store._profile_path_for_mod(mod_path)
        if hasattr(self, "readiness_tree"):
            self.refresh_current_project_readiness()

    def _build_readiness_rows(self, findings):
        rows = []
        if not findings:
            return rows

        for path, issue_type, detail, line in findings["issues"]:
            rows.append(("Fixable" if issue_type == "Missing Fields" else "Warning", issue_type, f"{os.path.basename(path)}:{line} {detail}"))
        for detail in findings["validation_errors"]:
            rows.append(("Blocking", "Validation", detail))
        for detail in findings["validation_warnings"]:
            rows.append(("Warning", "Validation", detail))
        for path in findings["trn_duplicate_headers"]:
            rows.append(("Fixable", "TRN Duplicate", os.path.basename(path)))
        for path in findings["trn_line_endings"]:
            rows.append(("Fixable", "TRN Line Endings", os.path.basename(path)))
        for path in findings["legacy_files"]:
            rows.append(("Fixable", "Legacy File", os.path.basename(path)))
        if not rows:
            rows.append(("Ready", "Scan", "No blocking issues detected."))
        return rows

    def _summarize_readiness(self, findings):
        rows = self._build_readiness_rows(findings)
        counts = {"Blocking": 0, "Fixable": 0, "Warning": 0, "Ready": 0}
        for severity, _issue_type, _detail in rows:
            counts[severity] = counts.get(severity, 0) + 1
        summary = f"Readiness: {counts['Blocking']} blocking, {counts['Fixable']} fixable, {counts['Warning']} warnings"
        detail = "Ready to publish." if rows and rows[0][0] == "Ready" else "Resolve blocking items or use one-click fixes before publishing."
        return summary, detail, rows

    def _update_project_status(self, inventory=None):
        project = self.current_project_data or {}
        item_id = self.item_id_var.get().strip()
        if item_id.isdigit() and item_id != "0":
            self.publish_target_var.set(f"TARGET: UPDATE ITEM {item_id}")
        else:
            self.publish_target_var.set("TARGET: CREATE NEW ITEM")

        last_upload_at = project.get("last_upload_at")
        if last_upload_at:
            date_text = last_upload_at.replace("T", " ").split(".", 1)[0]
            self.last_upload_var.set(f"LAST PUBLISH: {date_text}")
        else:
            self.last_upload_var.set("LAST PUBLISH: NONE")

        if inventory is not None:
            changed = self._count_changed_files(inventory, project.get("last_upload_inventory"))
            self.changed_since_upload_var.set(f"CHANGED FILES: {changed}")
        else:
            self.changed_since_upload_var.set("CHANGED FILES: UNKNOWN")

    def refresh_current_project_readiness(self):
        mod_dir = self.mod_path.get().strip()
        if not hasattr(self, "readiness_tree"):
            return None
        self.readiness_tree.delete(*self.readiness_tree.get_children())
        if not mod_dir or not os.path.exists(mod_dir):
            self.current_inventory = []
            self.current_findings = None
            self.current_readiness = None
            self.readiness_summary_var.set("Readiness: Select a content folder.")
            self.readiness_detail_var.set("")
            self._update_project_status([])
            return None

        inventory = self._build_mod_inventory(mod_dir)
        findings = self._collect_mod_findings(mod_dir, inventory=inventory)
        self.current_inventory = inventory
        self.current_findings = findings
        self.current_project_signature = self._fingerprint_inventory(inventory)
        summary, detail, rows = self._summarize_readiness(findings)
        self.current_readiness = rows
        self.readiness_summary_var.set(summary)
        self.readiness_detail_var.set(detail)
        for severity, issue_type, text in rows:
            self.readiness_tree.insert("", "end", values=(severity, issue_type, text))
        self._update_project_status(inventory)
        return findings

    def _build_publish_plan(self, content, preview, use_cached_creds, findings, inventory):
        auth_mode = "Cached credentials" if use_cached_creds else f"Manual login ({self.username_var.get().strip()})"
        item_id = self.item_id_var.get().strip()
        mode = f"UPDATE ({item_id})" if item_id.isdigit() and item_id != "0" else "CREATE NEW"
        blockers = list(findings["validation_errors"])
        warnings = list(findings["validation_warnings"])
        warnings.extend(
            [f"{len(findings['issues'])} scanner issues found."] if findings["issues"] else []
        )
        fixups = []
        if findings["issues"]:
            fixups.append(("scanner", "Apply available scanner quick fixes"))
        if findings["trn_duplicate_headers"]:
            fixups.append(("trn_duplicates", f"Remove duplicate [Size] headers in {len(findings['trn_duplicate_headers'])} TRN files"))
        if findings["trn_line_endings"]:
            fixups.append(("trn_endings", f"Normalize CRLF line endings in {len(findings['trn_line_endings'])} TRN files"))
        if findings["legacy_files"]:
            fixups.append(("legacy_files", f"Delete {len(findings['legacy_files'])} legacy .map files"))

        changed = self._count_changed_files(inventory, self.current_project_data.get("last_upload_inventory"))
        return {
            "mode": mode,
            "item_id": item_id or "0",
            "auth_mode": auth_mode,
            "content": os.path.abspath(content),
            "preview": os.path.abspath(preview),
            "title": self.title_var.get(),
            "visibility": self._normalize_visibility_value(self.visibility_var.get()),
            "change_note": self.note_var.get().strip(),
            "changed_files": changed,
            "blockers": blockers,
            "warnings": warnings,
            "fixups": fixups,
        }

    def _apply_publish_fixups(self, findings, selected_fixup_keys):
        if "scanner" in selected_fixup_keys and findings["issues"]:
            self.apply_quick_fixes(findings["issues"])
        if "trn_duplicates" in selected_fixup_keys and findings["trn_duplicate_headers"]:
            self.fix_trn_duplicates(findings["trn_duplicate_headers"])
        if "trn_endings" in selected_fixup_keys and findings["trn_line_endings"]:
            self.fix_trn_files(findings["trn_line_endings"])
        if "legacy_files" in selected_fixup_keys and findings["legacy_files"]:
            self.delete_legacy_files(findings["legacy_files"])
        return self.refresh_current_project_readiness()

    def _confirm_publish_review(self, plan, findings):
        wait_window = getattr(self.root, "wait_window", None)
        if wait_window is None or type(wait_window).__name__ == "MagicMock":
            return True, [key for key, _label in plan["fixups"]]

        if not plan["fixups"] and not plan["warnings"] and not plan["blockers"]:
            return True, []

        win = tk.Toplevel(self.root)
        win.title("Review Publish Plan")
        win.geometry("860x620")
        win.configure(bg="#1a1a1a")
        ttk.Label(win, text="REVIEW AND PUBLISH", font=(self.current_font, 14, "bold"), foreground=self.colors["highlight"], background="#1a1a1a").pack(anchor="w", padx=12, pady=(12, 6))

        summary = tk.Text(win, height=10, bg="#050505", fg="#d4d4d4", insertbackground="#d4d4d4", font=("Consolas", 10))
        summary.pack(fill="x", padx=12, pady=(0, 10))
        lines = [
            f"Mode: {plan['mode']}",
            f"Title: {plan['title']}",
            f"Visibility: {plan['visibility']}",
            f"Content: {plan['content']}",
            f"Preview: {plan['preview']}",
            f"Auth: {plan['auth_mode']}",
            f"Changed files since last publish: {plan['changed_files']}",
            f"Change note: {plan['change_note'] or '(empty)'}",
            "",
            f"Blocking: {len(plan['blockers'])}",
            f"Fixable: {len(plan['fixups'])}",
            f"Warnings: {len(plan['warnings'])}",
        ]
        summary.insert("1.0", "\n".join(lines))
        summary.config(state="disabled")

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        left = ttk.LabelFrame(body, text=" FIXES ", padding=10)
        left.pack(side="left", fill="y", padx=(0, 10))
        selected_fixups = {}
        for key, label in plan["fixups"]:
            var = tk.BooleanVar(value=True)
            selected_fixups[key] = var
            ttk.Checkbutton(left, text=label, variable=var).pack(anchor="w")
        if not selected_fixups:
            ttk.Label(left, text="No one-click fixes available.").pack(anchor="w")

        right = ttk.LabelFrame(body, text=" FINDINGS ", padding=10)
        right.pack(side="left", fill="both", expand=True)
        findings_tree = ttk.Treeview(right, columns=("Severity", "Detail"), show="headings")
        findings_tree.heading("Severity", text="Severity")
        findings_tree.heading("Detail", text="Detail")
        findings_tree.column("Severity", width=90, anchor="center")
        findings_tree.column("Detail", width=520)
        findings_tree.pack(fill="both", expand=True)

        for blocker in plan["blockers"]:
            findings_tree.insert("", "end", values=("Blocking", blocker))
        for warning in plan["warnings"]:
            findings_tree.insert("", "end", values=("Warning", warning))
        for severity, issue_type, detail in self._build_readiness_rows(findings):
            if severity in ("Ready",):
                continue
            findings_tree.insert("", "end", values=(severity, f"{issue_type}: {detail}"))

        result = {"publish": False, "fixups": []}

        def publish():
            result["publish"] = True
            result["fixups"] = [key for key, var in selected_fixups.items() if var.get()]
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="CANCEL", command=win.destroy).pack(side="right")
        if plan["blockers"]:
            ttk.Button(btns, text="PUBLISH ANYWAY", command=publish).pack(side="right", padx=6)
        else:
            ttk.Button(btns, text="PUBLISH", command=publish, style="Success.TButton").pack(side="right", padx=6)

        win.transient(self.root)
        win.grab_set()
        self.root.wait_window(win)
        return result["publish"], result["fixups"]

    def _get_mod_scanner(self):
        self.mod_scanner.resource_dir = self.resource_dir
        self.mod_scanner.logger = self.log
        return self.mod_scanner

    def _get_steam_service(self):
        self.steam_service.logger = self.log
        return self.steam_service

    def _get_workshop_backend(self):
        self.workshop_backend.logger = self.log
        self.workshop_backend.steam_service = self._get_steam_service()
        return self.workshop_backend

    def _get_memory_analyzer(self):
        self.memory_analyzer.logger = self.log
        self.memory_analyzer.has_pil = HAS_PIL
        self.memory_analyzer.image_module = Image if HAS_PIL else None
        return self.memory_analyzer

    def _get_content_fixer(self):
        self.content_fixer.logger = self.log
        return self.content_fixer

    def _get_file_manager(self):
        self.file_manager.logger = self.log
        self.file_manager.has_pil = HAS_PIL
        self.file_manager.image_module = Image if HAS_PIL else None
        return self.file_manager

    def _get_upload_preflight(self):
        self.upload_preflight.logger = self.log
        return self.upload_preflight

    def _get_steamworks_tag_updater(self):
        self.steamworks_tag_updater.logger = self.log
        return self.steamworks_tag_updater

    def _load_api_key_from_secure_store(self):
        if not HAS_KEYRING:
            return
        try:
            value = keyring.get_password(KEYRING_SERVICE, KEYRING_API_KEY_ACCOUNT)
            if value:
                self.api_key_var.set(value)
        except Exception:
            pass

    def _save_api_key_to_secure_store(self):
        value = self.api_key_var.get().strip()
        if not HAS_KEYRING:
            if value and not self._warned_no_keyring:
                self._warned_no_keyring = True
                self.log("Secure key storage unavailable (install 'keyring'). API key is not persisted.")
            return
        try:
            if value:
                keyring.set_password(KEYRING_SERVICE, KEYRING_API_KEY_ACCOUNT, value)
            else:
                try:
                    keyring.delete_password(KEYRING_SERVICE, KEYRING_API_KEY_ACCOUNT)
                except Exception:
                    pass
        except Exception as e:
            self.log(f"Secure key storage error: {e}")

    def _set_busy(self, operation, is_busy):
        with self._busy_lock:
            if is_busy:
                self._active_operations.add(operation)
            else:
                self._active_operations.discard(operation)
            active = sorted(self._active_operations)
        status_text = "STATUS: IDLE" if not active else f"STATUS: BUSY ({', '.join(active)})"
        self.root.after(0, lambda: self._apply_busy_state(status_text, bool(active)))

    def _apply_busy_state(self, status_text, is_busy):
        self.busy_status_var.set(status_text)
        global_state = "disabled" if is_busy else "normal"

        for name in ("upload_btn", "refresh_btn", "manage_set_target_btn", "manage_update_btn", "manage_detect_btn", "manage_owner_entry"):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.config(state=global_state)
                except Exception:
                    pass

        if hasattr(self, "tree"):
            try:
                self.tree.configure(selectmode="none" if is_busy else "browse")
            except Exception:
                pass

        # Respect cached-credential mode and busy mode simultaneously.
        self._toggle_auth_fields()

    def on_close(self):
        self.save_config()
        # Cancel any active QR polling
        if getattr(self, "qr_poll_timer", None):
            self.root.after_cancel(self.qr_poll_timer)

        # Kill SteamCMD process if running
        if self.steamcmd_process and self.steamcmd_process.poll() is None:
            try:
                self.steamcmd_process.terminate()
            except: pass

        # Clean up temp preview files
        try:
            for f in os.listdir(self.temp_dir): os.remove(os.path.join(self.temp_dir, f))
            os.rmdir(self.temp_dir)
        except Exception: pass
        self.root.destroy()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        
        c = self.colors
        main_font = ("Consolas", 10)
        bold_font = ("Consolas", 10, "bold")
        display_font = (self.current_font, 11, "bold")
        
        style.configure(".", background=c["bg"], foreground=c["fg"], font=main_font, bordercolor=c["dark_highlight"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#1a1a1a", foreground=c["fg"], padding=[10, 2])
        style.map("TNotebook.Tab", background=[("selected", c["dark_highlight"])], foreground=[("selected", c["highlight"])])
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["highlight"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["highlight"], font=display_font)
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("TEntry", fieldbackground="#1a1a1a", foreground=c["accent"], insertcolor=c["highlight"])
        style.configure("TButton", background="#1a1a1a", foreground=c["fg"])
        style.map("TButton", background=[("active", c["dark_highlight"])], foreground=[("active", c["highlight"])])
        style.configure("Success.TButton", foreground=c["highlight"], font=bold_font)
        style.configure("TCombobox", fieldbackground="#1a1a1a", foreground=c["accent"], arrowcolor=c["highlight"])
        style.map("TCombobox", fieldbackground=[("readonly", "#1a1a1a")], foreground=[("readonly", c["accent"])])
        style.configure("Treeview", background="#0a0a0a", foreground=c["fg"], fieldbackground="#0a0a0a", rowheight=25)
        style.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", "#000000")])

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding=16)
        main_frame.pack(fill="both", expand=True)

        header = ttk.Frame(main_frame)
        header.pack(fill="x", pady=(0, 12))

        ttk.Label(
            header,
            text="WORKSHOP COMMAND",
            font=(self.current_font, 20, "bold"),
            foreground=self.colors["highlight"],
        ).pack(side="left")

        header_meta = ttk.Frame(header)
        header_meta.pack(side="right")
        ttk.Label(header_meta, textvariable=self.publish_target_var, foreground="#ffcc66").pack(anchor="e")
        ttk.Label(header_meta, textvariable=self.last_upload_var).pack(anchor="e")
        ttk.Label(header_meta, textvariable=self.changed_since_upload_var, foreground="#ffff44").pack(anchor="e")

        top_bar = ttk.Frame(main_frame)
        top_bar.pack(fill="x", pady=(0, 10))
        ttk.Label(top_bar, text="Target Game:").pack(side="left")
        self.game_combo = ttk.Combobox(top_bar, textvariable=self.game_var, values=list(self.games.keys()), state="readonly", width=12)
        self.game_combo.pack(side="left", padx=(8, 20))
        ttk.Label(top_bar, textvariable=self.busy_status_var, foreground="#ffff44").pack(side="right")
        ttk.Label(top_bar, textvariable=self.project_hint_var, foreground=self.colors["accent"]).pack(side="right", padx=(0, 20))

        body = ttk.Frame(main_frame)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=5)
        body.columnconfigure(2, weight=4)
        body.rowconfigure(0, weight=1)

        left_col = ttk.Frame(body)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        center_col = ttk.Frame(body)
        center_col.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        right_col = ttk.Frame(body)
        right_col.grid(row=0, column=2, sticky="nsew")

        self.setup_project_panel(left_col)
        self.setup_library_panel(left_col)
        self.setup_access_panel(center_col)
        self.setup_editor_panel(center_col)
        self.setup_readiness_panel(right_col)
        self.setup_activity_panel(right_col)

        self.notebook = None
        self.upload_tab = None
        self.manage_tab = None

    def setup_project_panel(self, parent):
        frame = ttk.LabelFrame(parent, text=" PROJECTS ", padding=10)
        frame.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Label(frame, textvariable=self.project_name_var, font=(self.current_font, 12, "bold"), foreground=self.colors["highlight"]).pack(anchor="w")
        ttk.Label(frame, text="Saved local projects paired to Workshop items when available.", foreground=self.colors["fg"]).pack(anchor="w", pady=(2, 8))

        filter_row = ttk.Frame(frame)
        filter_row.pack(fill="x", pady=(0, 6))
        ttk.Label(filter_row, text="Filter:").pack(side="left")
        filter_entry = ttk.Entry(filter_row, textvariable=self.project_filter_var)
        filter_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        filter_entry.bind("<KeyRelease>", lambda _e: self.refresh_recent_projects())

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        self.project_tree = ttk.Treeview(tree_frame, columns=("Name", "Item", "Updated"), show="headings", height=10)
        self.project_tree.heading("Name", text="Project")
        self.project_tree.heading("Item", text="Workshop ID")
        self.project_tree.heading("Updated", text="Last Opened")
        self.project_tree.column("Name", width=180)
        self.project_tree.column("Item", width=90, anchor="center")
        self.project_tree.column("Updated", width=120, anchor="center")
        prj_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=prj_scroll.set)
        self.project_tree.pack(side="left", fill="both", expand=True)
        prj_scroll.pack(side="right", fill="y")
        self.project_tree.bind("<Double-1>", lambda _e: self.open_selected_project())

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="OPEN", command=self.open_selected_project).pack(side="left")
        ttk.Button(btn_row, text="SAVE", command=self.save_current_project_state).pack(side="left", padx=4)
        ttk.Button(btn_row, text="EXPORT", command=self.save_profile).pack(side="right")
        ttk.Button(btn_row, text="IMPORT", command=self.load_profile).pack(side="right", padx=4)

    def setup_library_panel(self, parent):
        frame = ttk.LabelFrame(parent, text=" WORKSHOP LIBRARY ", padding=10)
        frame.pack(fill="both", expand=True)

        ctrl_row = ttk.Frame(frame)
        ctrl_row.pack(fill="x", pady=(0, 6))
        self.refresh_btn = ttk.Button(ctrl_row, text="REFRESH", command=self.refresh_workshop_items)
        self.refresh_btn.pack(side="left")
        self.manage_set_target_btn = ttk.Button(ctrl_row, text="PAIR", command=self.use_selected_item_id_for_upload)
        self.manage_set_target_btn.pack(side="left", padx=4)
        self.manage_update_btn = ttk.Button(ctrl_row, text="LOAD DETAILS", command=self.prepare_update)
        self.manage_update_btn.pack(side="left")

        identity_row = ttk.Frame(frame)
        identity_row.pack(fill="x", pady=(0, 6))
        ttk.Label(identity_row, text="Owner:").pack(side="left")
        self.manage_owner_entry = ttk.Entry(identity_row, textvariable=self.manage_identity_var)
        self.manage_owner_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.manage_detect_btn = ttk.Button(identity_row, text="USE CURRENT LOGIN", command=self.use_local_steam_identity)
        self.manage_detect_btn.pack(side="left")

        ttk.Label(frame, textvariable=self.library_status_var, foreground="#ffff44").pack(anchor="w", pady=(0, 6))

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("Title", "ID", "Visibility", "Updated"), show="headings", height=10)
        self.tree.heading("Title", text="Title")
        self.tree.heading("ID", text="Workshop ID")
        self.tree.heading("Visibility", text="Visibility")
        self.tree.heading("Updated", text="Updated")
        self.tree.column("Title", width=220)
        self.tree.column("ID", width=110, anchor="center")
        self.tree.column("Visibility", width=90, anchor="center")
        self.tree.column("Updated", width=120, anchor="center")
        lib_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=lib_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        lib_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_manage_selection)
        self.tree.bind("<Double-1>", lambda _e: self.prepare_update())

    def setup_access_panel(self, parent):
        frame = ttk.LabelFrame(parent, text=" ACCESS ", padding=10)
        frame.pack(fill="x", pady=(0, 10))
        frame.columnconfigure(1, weight=3)
        frame.columnconfigure(3, weight=2)

        ttk.Label(frame, text="SteamCMD Path:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.steamcmd_path).grid(row=0, column=1, sticky="ew", padx=5)
        path_actions = ttk.Frame(frame)
        path_actions.grid(row=0, column=2, columnspan=2, sticky="e")
        ttk.Button(path_actions, text="BROWSE", command=self.browse_steamcmd).pack(side="left")
        ttk.Button(path_actions, text="AUTO-DL", command=self.download_steamcmd).pack(side="left", padx=(5, 0))

        ttk.Label(frame, text="Steam Username:").grid(row=1, column=0, sticky="w", pady=5)
        self.user_entry = ttk.Entry(frame, textvariable=self.username_var)
        self.user_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        ttk.Label(frame, text="Password:").grid(row=1, column=2, sticky="e", pady=5)
        self.pwd_entry = ttk.Entry(frame, textvariable=self.password_var, show="*")
        self.pwd_entry.grid(row=1, column=3, sticky="ew", padx=(5, 0), pady=5)

        ttk.Label(frame, text="2FA Code:").grid(row=2, column=0, sticky="w")
        self.guard_entry = ttk.Entry(frame, textvariable=self.steam_guard_var, width=12)
        self.guard_entry.grid(row=2, column=1, sticky="w", padx=5)

        auth_row = ttk.Frame(frame)
        auth_row.grid(row=2, column=2, columnspan=2, sticky="w")
        self.qr_btn = ttk.Button(auth_row, text="LOGIN WITH QR", command=self.start_qr_login)
        self.qr_btn.pack(side="left")
        cached_cb = ttk.Checkbutton(auth_row, text="USE CACHED LOGIN", variable=self.use_cached_creds_var)
        cached_cb.pack(side="left", padx=10)

        ttk.Label(frame, text="Steam Web API Key:").grid(row=3, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(frame, textvariable=self.api_key_var, show="*").grid(row=3, column=1, sticky="ew", padx=5, pady=(5, 0))
        ttk.Button(frame, text="?", command=self.open_api_key_link, width=3).grid(row=3, column=2, sticky="w", padx=(0, 5), pady=(5, 0))
        native_appid_cb = ttk.Checkbutton(frame, text="NATIVE TAGS VIA steam_appid.txt", variable=self.experimental_native_appid_var)
        native_appid_cb.grid(row=4, column=1, columnspan=3, sticky="w", pady=(5, 0))

    def setup_editor_panel(self, parent):
        frame = ttk.LabelFrame(parent, text=" PROJECT WORKSPACE ", padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=3)
        frame.columnconfigure(3, weight=2)

        top_row = ttk.Frame(frame)
        top_row.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        self.upload_mode_label = ttk.Label(top_row, text="", foreground=self.colors["highlight"], font=(self.current_font, 11, "bold"))
        self.upload_mode_label.pack(side="left")
        ttk.Button(top_row, text="NEW TARGET", command=self.set_create_mode).pack(side="right")
        ttk.Button(top_row, text="OPEN PAGE", command=self.open_workshop_page).pack(side="right", padx=4)

        ttk.Label(frame, text="Content Folder:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.mod_path).grid(row=1, column=1, columnspan=3, sticky="ew", padx=5)
        path_btns = ttk.Frame(frame)
        path_btns.grid(row=2, column=1, columnspan=3, sticky="w", pady=(4, 8))
        ttk.Button(path_btns, text="BROWSE", command=self.browse_content).pack(side="left")
        ttk.Button(path_btns, text="NEW", command=self.open_template_wizard).pack(side="left", padx=4)
        ttk.Button(path_btns, text="ANALYZE", command=self.analyze_memory_usage).pack(side="left")
        ttk.Button(path_btns, text="RESCAN", command=self.refresh_current_project_readiness).pack(side="left", padx=4)

        watch_row = ttk.Frame(frame)
        watch_row.grid(row=3, column=1, columnspan=3, sticky="w", pady=(0, 8))
        watch_cb = ttk.Checkbutton(watch_row, text="WATCH FOR CHANGES", variable=self.watch_mode_var, command=self.toggle_watch_mode)
        watch_cb.pack(side="left")

        ttk.Label(frame, text="Preview Image:").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.preview_path).grid(row=4, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        ttk.Button(frame, text="BROWSE", command=self.browse_preview).grid(row=4, column=3, sticky="e", pady=5)

        ttk.Label(frame, text="Title:").grid(row=5, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.title_var).grid(row=5, column=1, columnspan=2, sticky="ew", padx=5)
        self.title_char_label = ttk.Label(frame, text=f"0 / {STEAM_TITLE_LIMIT}")
        self.title_char_label.grid(row=5, column=3, sticky="w")

        ttk.Label(frame, text="Description:").grid(row=6, column=0, sticky="nw", pady=5)
        self.desc_text = tk.Text(frame, height=10, bg="#1a1a1a", fg=self.colors["accent"], insertbackground=self.colors["highlight"], font=("Consolas", 10))
        self.desc_text.grid(row=6, column=1, columnspan=3, sticky="nsew", padx=5, pady=5)
        self.desc_text.bind("<KeyRelease>", self._update_desc_counter)

        self.desc_char_label = ttk.Label(frame, text=f"0 / {STEAM_DESC_LIMIT}")
        self.desc_char_label.grid(row=7, column=3, sticky="e", padx=5)

        ttk.Label(frame, text="Visibility:").grid(row=8, column=0, sticky="w", pady=5)
        ttk.Combobox(frame, textvariable=self.visibility_var, values=["0 (Public)", "1 (Friends)", "2 (Private)"], state="readonly", width=16).grid(row=8, column=1, sticky="w", padx=5, pady=5)
        ttk.Label(frame, text="Workshop ID:").grid(row=8, column=2, sticky="e")
        ttk.Entry(frame, textvariable=self.item_id_var, width=18).grid(row=8, column=3, sticky="w", padx=5)

        ttk.Label(frame, text="Change Note:").grid(row=9, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.note_var).grid(row=9, column=1, columnspan=3, sticky="ew", padx=5)

        ttk.Label(frame, text="Tags:").grid(row=10, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.tags_var).grid(row=10, column=1, columnspan=3, sticky="ew", padx=5)

        actions = ttk.Frame(frame)
        actions.grid(row=11, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self.upload_btn = ttk.Button(actions, text="REVIEW AND PUBLISH", command=self.start_upload, style="Success.TButton")
        self.upload_btn.pack(side="left", fill="x", expand=True, ipady=6)
        self.logs_btn = ttk.Button(actions, text="STEAM LOGS", command=self.show_steam_logs)
        self.logs_btn.pack(side="right", padx=(6, 0))

        self._update_upload_mode_indicator()

    def setup_readiness_panel(self, parent):
        frame = ttk.LabelFrame(parent, text=" READINESS ", padding=10)
        frame.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Label(frame, textvariable=self.readiness_summary_var, foreground=self.colors["highlight"], font=(self.current_font, 12, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.readiness_detail_var, foreground=self.colors["fg"], justify="left").pack(anchor="w", pady=(4, 8))

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        self.readiness_tree = ttk.Treeview(tree_frame, columns=("Severity", "Type", "Detail"), show="headings")
        self.readiness_tree.heading("Severity", text="Severity")
        self.readiness_tree.heading("Type", text="Type")
        self.readiness_tree.heading("Detail", text="Detail")
        self.readiness_tree.column("Severity", width=90, anchor="center")
        self.readiness_tree.column("Type", width=120, anchor="center")
        self.readiness_tree.column("Detail", width=340)
        readiness_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.readiness_tree.yview)
        self.readiness_tree.configure(yscrollcommand=readiness_scroll.set)
        self.readiness_tree.pack(side="left", fill="both", expand=True)
        readiness_scroll.pack(side="right", fill="y")

    def setup_activity_panel(self, parent):
        frame = ttk.LabelFrame(parent, text=" ACTIVITY ", padding=10)
        frame.pack(fill="both", expand=True)

        self.log_box = tk.Text(frame, height=12, state="disabled", bg="#050505", fg=self.colors["fg"], font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True)

    def _update_title_counter(self, *args):
        count = len(self.title_var.get())
        if hasattr(self, "title_char_label"):
            self.title_char_label.config(text=f"{count} / {STEAM_TITLE_LIMIT}")
            if count > STEAM_TITLE_LIMIT:
                self.title_char_label.config(foreground="red")
            else:
                self.title_char_label.config(foreground=self.colors["fg"])

    def _update_desc_counter(self, *args):
        count = len(self._get_desc_text_value())
        if hasattr(self, "desc_char_label"):
            self.desc_char_label.config(text=f"{count} / {STEAM_DESC_LIMIT}")
            if count > STEAM_DESC_LIMIT:
                self.desc_char_label.config(foreground="red")
            else:
                self.desc_char_label.config(foreground=self.colors["fg"])

    def _update_upload_mode_indicator(self, *args):
        item_id = self.item_id_var.get().strip()
        is_update = item_id.isdigit() and item_id != "0"
        text = f"MODE: UPDATE EXISTING ITEM ({item_id})" if is_update else "MODE: CREATE NEW ITEM"
        color = "#ffcc66" if is_update else self.colors["highlight"]
        if hasattr(self, "upload_mode_label"):
            self.upload_mode_label.config(text=text, foreground=color)
        if hasattr(self, "publish_target_var"):
            self.publish_target_var.set(f"TARGET: UPDATE ITEM {item_id}" if is_update else "TARGET: CREATE NEW ITEM")

    def set_create_mode(self):
        self.item_id_var.set("0")
        self.log("Upload mode set to CREATE NEW ITEM.")

    def _friendly_api_error(self, error=None, response=None):
        return self._get_steam_service().friendly_api_error(error=error, response=response)

    def _request_with_retry(self, method, url, operation_name="request", timeout=10, attempts=REQUEST_RETRY_ATTEMPTS, backoff=REQUEST_BACKOFF_SECONDS, **kwargs):
        return self._get_steam_service().request_with_retry(
            method,
            url,
            operation_name=operation_name,
            timeout=timeout,
            attempts=attempts,
            backoff=backoff,
            **kwargs,
        )

    def _vdf_escape(self, value):
        return self._get_steam_service().vdf_escape(value)

    def _build_upload_vdf_content(self, appid, publishedfileid, contentfolder, previewfile, visibility, title, description, changenote):
        return self._get_steam_service().build_upload_vdf_content(
            appid=appid,
            publishedfileid=publishedfileid,
            contentfolder=contentfolder,
            previewfile=previewfile,
            visibility=visibility,
            title=title,
            description=description,
            changenote=changenote,
        )

    def _confirm_upload_plan(self, content, preview, use_cached_creds):
        item_id = self.item_id_var.get().strip()
        auth_mode = "Cached credentials" if use_cached_creds else f"Manual login ({self.username_var.get().strip()})"
        prompt = self._get_content_fixer().build_upload_plan_prompt(
            item_id=item_id,
            game_name=self.game_var.get(),
            appid=self.games[self.game_var.get()]["appid"],
            visibility=self.visibility_var.get(),
            title=self.title_var.get(),
            content=content,
            preview=preview,
            auth_mode=auth_mode,
            manage_owner=self.manage_identity_var.get().strip(),
            change_note=self.note_var.get().strip(),
        )
        return messagebox.askyesno("Confirm Upload Plan", prompt)

    def _tokenize_vdf(self, text):
        return self._get_steam_service().tokenize_vdf(text)

    def _parse_vdf_tokens(self, tokens, start_index=0, expect_closing=False):
        return self._get_steam_service().parse_vdf_tokens(tokens, start_index=start_index, expect_closing=expect_closing)

    def _parse_vdf_text(self, text):
        return self._get_steam_service().parse_vdf_text(text)

    def _dict_get_ci(self, dct, key, default=""):
        return self._get_steam_service().dict_get_ci(dct, key, default=default)

    def open_api_key_link(self):
        webbrowser.open("https://steamcommunity.com/dev/apikey")

    def resize_preview_image(self, image_path):
        try:
            return self._get_file_manager().resize_preview_image(image_path, self.temp_dir)
        except Exception as e:
            self.log(f"Error resizing image: {e}")
        return None

    def save_profile(self):
        f = filedialog.asksaveasfilename(initialdir=self.profiles_dir, defaultextension=".json", filetypes=[("JSON Profile", "*.json")])
        if not f: return
        
        data = {
            "mod_path": self.mod_path.get(),
            "preview_path": self.preview_path.get(),
            "title": self.title_var.get(),
            "description": self._get_desc_text_value(),
            "visibility": self._normalize_visibility_value(self.visibility_var.get()),
            "item_id": self.item_id_var.get(),
            "change_note": self.note_var.get(),
            "tags": self.tags_var.get(),
            "project_name": os.path.basename(self.mod_path.get().rstrip("\\/")) if self.mod_path.get() else "project",
        }
        try:
            self._get_file_manager().save_profile(f, data)
            self.log(f"Profile saved: {os.path.basename(f)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def load_profile(self):
        f = filedialog.askopenfilename(initialdir=self.profiles_dir, filetypes=[("JSON Profile", "*.json")])
        if not f: return
        
        try:
            data = self._get_file_manager().load_profile(f)
            self.mod_path.set(data.get("mod_path", ""))
            self.preview_path.set(data.get("preview_path", ""))
            self.title_var.set(data.get("title", ""))
            self._set_desc_text_value(data.get("description", ""))
            self.visibility_var.set(self._normalize_visibility_value(data.get("visibility", "0 (Public)")))
            self.item_id_var.set(data.get("item_id", "0"))
            self.note_var.set(data.get("change_note", ""))
            self.tags_var.set(data.get("tags", ""))
            self.current_project_profile_path = f if os.path.dirname(os.path.abspath(f)) == os.path.abspath(self.profiles_dir) else ""
            self.current_project_data = data
            self.refresh_current_project_readiness()
            self.log(f"Profile loaded: {os.path.basename(f)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load profile: {e}")

    def log(self, msg):
        self.root.after(0, lambda: self._log_impl(msg))

    def _log_impl(self, msg):
        if not hasattr(self, "log_box"):
            return
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"> {msg}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def browse_steamcmd(self):
        f = filedialog.askopenfilename(filetypes=[("Executable", "*.exe")])
        if f: self.steamcmd_path.set(f)

    def download_steamcmd(self):
        if not messagebox.askyesno("Confirm Download", "This will download SteamCMD from Valve's servers and extract it to a 'steamcmd' folder in your app directory. Continue?"):
            return
            
        self.log("Downloading SteamCMD zip...")
        
        def _worker():
            try:
                exe_path = self._get_file_manager().download_steamcmd(self.base_dir, self._request_with_retry)
                self.root.after(0, lambda: self.steamcmd_path.set(exe_path))
                self.log("SteamCMD successfully downloaded and extracted.")
                self.root.after(0, lambda: messagebox.showinfo("Success", "SteamCMD downloaded and path set automatically."))
            except Exception as e:
                self.log(f"Download Error: {e}")
                self.root.after(0, lambda: messagebox.showerror("Download Error", f"Failed to download SteamCMD: {e}"))
                
        threading.Thread(target=_worker, daemon=True).start()

    def open_template_wizard(self):
        TemplateWizard(self.root, self.colors, on_success=self._handle_new_project_created)

    def toggle_watch_mode(self):
        if self.watch_mode_var.get():
            self.log("Watch Mode enabled.")
            self.last_watch_signature = None
            self.last_watch_summary = None
            if not self.watch_thread or not self.watch_thread.is_alive():
                self.watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
                self.watch_thread.start()
        else:
            self.log("Watch Mode disabled.")
            self.last_watch_signature = None
            self.last_watch_summary = None

    def _watch_loop(self):
        import time
        while self.watch_mode_var.get():
            mod_dir = self.mod_path.get()
            if mod_dir and os.path.exists(mod_dir):
                try:
                    inventory = self._build_mod_inventory(mod_dir)
                    current_signature = self._fingerprint_inventory(inventory)

                    if self.last_watch_signature is None:
                        self.last_watch_signature = current_signature
                        self.root.after(0, self.refresh_current_project_readiness)
                    elif current_signature != self.last_watch_signature:
                        self.last_watch_signature = current_signature
                        self.log("Change detected! Scanning...")
                        findings = self._collect_mod_findings(mod_dir, inventory=inventory)
                        self.current_inventory = inventory
                        self.current_findings = findings
                        summary = (
                            len(findings["issues"]),
                            len(findings["validation_errors"]),
                            len(findings["validation_warnings"]),
                            len(findings["trn_line_endings"]),
                            len(findings["trn_duplicate_headers"]),
                            len(findings["legacy_files"]),
                        )
                        if summary != self.last_watch_summary:
                            self.last_watch_summary = summary
                            if any(summary):
                                self.log(
                                    "Watch Alert: "
                                    f"{summary[0]} safety issues, "
                                    f"{summary[1]} validation errors, "
                                    f"{summary[2]} warnings, "
                                    f"{summary[3]} TRN line-ending issues, "
                                    f"{summary[4]} duplicate TRN headers, "
                                    f"{summary[5]} legacy files."
                                )
                            else:
                                self.log("Watch: Files verified.")
                        self.root.after(0, self.refresh_current_project_readiness)
                except Exception as e:
                    self.log(f"Watch error: {e}")
            time.sleep(3)

    def browse_content(self):
        d = filedialog.askdirectory()
        if d:
            self.mod_path.set(d)
            self.refresh_current_project_readiness()

    def browse_preview(self):
        f = filedialog.askopenfilename(filetypes=[("Images", "*.jpg;*.png;*.jpeg")])
        if f: 
            self.preview_path.set(f)
            if not HAS_PIL:
                try:
                    if os.path.getsize(f) > 1024 * 1024:
                        messagebox.showwarning("Image Size", f"Warning: Preview image is > 1MB. PIL library not found for auto-resizing.")
                except Exception: pass
                return

            try:
                if os.path.getsize(f) > 1024 * 1024:
                    if messagebox.askyesno("Image Too Large", f"Preview image is > 1MB. Auto-resize and compress it?"):
                        new_path = self.resize_preview_image(f)
                        if new_path:
                            self.preview_path.set(new_path)
            except Exception as e: self.log(f"Image size check failed: {e}")

    def start_qr_login(self):
        """Starts the Steam QR Login process."""
        self.log("Initializing QR login...")
        try:
            res = self._get_steam_service().begin_qr_auth_session(
                device_friendly_name=f"BZR Uploader ({os.environ.get('COMPUTERNAME', 'Windows')})",
                platform_type=1,
                timeout=10,
            )
            
            client_id = res.get("client_id")
            challenge_url = res.get("challenge_url")
            
            if not client_id or not challenge_url:
                self.log("Error: Invalid response from Steam API.")
                return

            self.qr_session_id = client_id
            
            # Step 2: Show QR Window
            self.show_qr_window(challenge_url)
            
            # Step 3: Polling
            self.poll_qr_status()

        except Exception as e:
            self.log(f"Login Error: {e}")
            messagebox.showerror("QR Login Error", f"Failed to start QR session:\n{e}")

    def show_qr_window(self, challenge_url):
        self.qr_win = tk.Toplevel(self.root)
        self.qr_win.title("Steam QR Login")
        self.qr_win.geometry("400x520")
        self.qr_win.configure(bg="#1a1a1a")
        self.qr_win.resizable(False, False)
        
        ttk.Label(self.qr_win, text="SCAN WITH STEAM MOBILE APP", font=("Consolas", 12, "bold"), foreground=self.colors["highlight"], background="#1a1a1a").pack(pady=10)
        
        # QR Code Frame (Center aligned)
        qr_frame = tk.Frame(self.qr_win, bg="#ffffff", padx=10, pady=10)
        qr_frame.pack(pady=10)
        
        self.qr_label = tk.Label(qr_frame, text="Loading QR...", bg="#ffffff", fg="#000000")
        self.qr_label.pack()

        try:
            if HAS_PIL and HAS_QRCODE:
                qr_img = qrcode.make(challenge_url).resize((250, 250))
                from PIL import ImageTk
                self.qr_img = ImageTk.PhotoImage(qr_img)
                self.qr_label.config(image=self.qr_img, text="")
            else:
                self.qr_label.config(text="QR display unavailable.\nOpen the Steam link manually.")
                self.log("QR image generation unavailable (install 'qrcode' and Pillow).")
        except Exception as e:
            self.qr_label.config(text=f"Failed to render QR\n{e}")

        ttk.Label(self.qr_win, text="1. Open Steam Mobile App\n2. Go to Steam Guard\n3. Select 'Scan a QR Code'", background="#1a1a1a", foreground="#d4d4d4", justify="left").pack(pady=10)
        link_box = tk.Text(self.qr_win, height=3, wrap="word", bg="#050505", fg="#d4d4d4", insertbackground="#d4d4d4", font=("Consolas", 9))
        link_box.pack(fill="x", padx=20, pady=(0, 10))
        link_box.insert("1.0", challenge_url)
        link_box.config(state="disabled")
        
        cancel_btn = ttk.Button(self.qr_win, text="CANCEL", command=self.cancel_qr_login)
        cancel_btn.pack(pady=(10, 20))
        
        self.qr_win.protocol("WM_DELETE_WINDOW", self.cancel_qr_login)
        self.qr_win.transient(self.root)
        self.qr_win.grab_set()

    def poll_qr_status(self):
        if not self.qr_session_id: return
        
        try:
            r = self._get_steam_service().poll_qr_auth_session(
                client_id=self.qr_session_id,
                request_id=self.qr_session_id,
                timeout=5,
            )
            if r.status_code == 404: # Session expired or invalid
                self.log("QR Session expired.")
                self.cancel_qr_login()
                return

            res = r.json().get("response", {})
            # Possible results: 
            # - Empty: still waiting
            # - refresh_token: success
            
            if res.get("refresh_token"):
                self.handle_qr_success(res)
                return
            
            # Poll again in 2 seconds
            self.qr_poll_timer = self.root.after(2000, self.poll_qr_status)
            
        except Exception as e:
            # Minor errors (timeout etc) are ignored during polling
            self.qr_poll_timer = self.root.after(2000, self.poll_qr_status)

    def handle_qr_success(self, res):
        self.log("QR Login Successful!")
        refresh_token = res.get("refresh_token")
        account_name = res.get("account_name")
        
        if account_name:
            self.username_var.set(account_name)
            
        # We don't have a secure way to store the refresh token for SteamCMD directly,
        # but we can use it to fetch more details or confirm login.
        # For now, we populate the username and tell the user they can use cached creds.
        
        messagebox.showinfo("Success", f"Logged in as {account_name}.\n\nYou can now use 'USE CACHED CREDENTIALS' or proceed.")
        
        if hasattr(self, 'qr_win'):
            self.qr_win.destroy()
        self.qr_session_id = None

    def cancel_qr_login(self):
        if self.qr_poll_timer:
            self.root.after_cancel(self.qr_poll_timer)
            self.qr_poll_timer = None
        self.qr_session_id = None
        if hasattr(self, 'qr_win'):
            self.qr_win.destroy()
        self.log("QR Login cancelled.")

    def _toggle_auth_fields(self, *args):
        is_busy = bool(self._active_operations)
        state = "disabled" if self.use_cached_creds_var.get() or is_busy else "normal"
        self.user_entry.config(state=state)
        self.pwd_entry.config(state=state)
        self.guard_entry.config(state=state)
        self.qr_btn.config(state=state)

    def _build_mod_inventory(self, mod_dir):
        return self._get_mod_scanner().build_inventory(mod_dir)

    def _fingerprint_inventory(self, inventory):
        return self._get_mod_scanner().fingerprint_inventory(inventory)

    def _collect_mod_findings(self, mod_dir, inventory=None):
        return self._get_mod_scanner().collect_findings(mod_dir, inventory=inventory)

    def analyze_memory_usage(self):
        mod_dir = self.mod_path.get()
        if not mod_dir or not os.path.exists(mod_dir):
            messagebox.showerror("Error", "Please select a valid content folder first.")
            return

        self.log("Analyzing memory footprint...")
        analysis = self._get_memory_analyzer().analyze(mod_dir)
        report = self._get_memory_analyzer().build_report(analysis)
        messagebox.showinfo("Memory Analysis", report)
        self.log(
            f"Analysis: Disk={analysis['disk_mb']:.1f}MB, "
            f"Est.Mem={analysis['vram_mb']:.1f}MB, "
            f"Orphans={len(analysis['orphans'])}"
        )

    def scan_mod_safety(self, mod_dir, inventory=None):
        return self._get_mod_scanner().scan_mod_safety(mod_dir, inventory=inventory)

    def scan_asset_references(self, mod_dir, inventory=None):
        return self._get_mod_scanner().scan_asset_references(mod_dir, inventory=inventory)

    def show_safety_warning(self, issues):
        win = tk.Toplevel(self.root)
        win.title("Safety Check - Suspicious ODF Headers")
        win.geometry("700x500")
        win.configure(bg="#1a1a1a")

        ttk.Label(win, text="⚠️ SECURITY WARNING", font=("Consolas", 14, "bold"), foreground="orange", background="#1a1a1a").pack(pady=(10, 5))
        ttk.Label(win, text="The following ODF files contain unrecognized headers.", foreground="#d4d4d4", background="#1a1a1a").pack()
        
        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        tree = ttk.Treeview(tree_frame, columns=("File", "Type", "Detail", "Line"), show="headings")
        tree.heading("File", text="File")
        tree.heading("Type", text="Issue Type")
        tree.heading("Detail", text="Detail")
        tree.heading("Line", text="Line")
        tree.column("File", width=200)
        tree.column("Type", width=100)
        tree.column("Detail", width=300)
        tree.column("Line", width=50, anchor="center")
        
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        
        issue_map = {}
        for row in self._get_upload_preflight().build_safety_rows(issues, self.mod_path.get()):
            item_id = tree.insert("", "end", values=(row["display_path"], row["issue_type"], row["detail"], row["line"]))
            issue_map[item_id] = row["full_path"]
            
        def on_open():
            sel = tree.selection()
            if sel:
                full_path = issue_map.get(sel[0])
                if full_path and os.path.exists(full_path):
                    try: os.startfile(full_path) if IS_WINDOWS else subprocess.call(['xdg-open', full_path])
                    except Exception as e: messagebox.showerror("Error", f"Could not open file: {e}", parent=win)

        def on_continue():
            win.result = True
            win.destroy()

        def on_quick_fix():
            count = self.apply_quick_fixes(issues)
            if count > 0:
                messagebox.showinfo("Quick Fix", f"Applied fixes to {count} issues.\nPlease re-scan or verify files.")
                win.destroy()
            else:
                messagebox.showinfo("Quick Fix", "No automatic fixes available for these specific issues.")

        win.result = False
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", pady=10, padx=10)
        ttk.Button(btn_frame, text="OPEN SELECTED FILE", command=on_open).pack(side="left")
        ttk.Button(btn_frame, text="QUICK FIX", command=on_quick_fix).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="CANCEL UPLOAD", command=win.destroy).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="IGNORE & CONTINUE", command=on_continue, style="Success.TButton").pack(side="right")
        
        win.transient(self.root)
        win.grab_set()
        self.root.wait_window(win)
        return getattr(win, 'result', False)

    def apply_quick_fixes(self, issues):
        return self._get_content_fixer().apply_quick_fixes(issues)

    def scan_trn_safety(self, mod_dir, inventory=None):
        return self._get_mod_scanner().scan_trn_safety(mod_dir, inventory=inventory)

    def scan_legacy_files(self, mod_dir, inventory=None):
        return self._get_mod_scanner().scan_legacy_files(mod_dir, inventory=inventory)

    def delete_legacy_files(self, files):
        return self._get_content_fixer().delete_legacy_files(files)

    def fix_trn_files(self, files):
        return self._get_content_fixer().fix_trn_files(files)

    def fix_trn_duplicates(self, files):
        return self._get_content_fixer().fix_trn_duplicates(files)

    def validate_content_structure(self, mod_dir):
        return self._get_mod_scanner().validate_content_structure(mod_dir)

    def open_workshop_page(self):
        item_id = self.item_id_var.get()
        if item_id and item_id != "0":
            webbrowser.open(f"https://steamcommunity.com/sharedfiles/filedetails/?id={item_id}")
        else:
            messagebox.showinfo("Info", "No valid Workshop ID available.")

    def update_item_id_from_vdf(self, vdf_path):
        try:
            if not os.path.exists(vdf_path):
                return None
            with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            match = re.search(r'"publishedfileid"\s+"(\d+)"', content)
            if not match:
                return None
            new_id = match.group(1)
            if new_id == "0":
                return None
            self.root.after(0, lambda value=new_id: self.item_id_var.set(value))
            self.log(f"Detected new Workshop ID: {new_id}")
            return new_id
        except Exception as e:
            self.log(f"Failed to parse VDF for ID: {e}")
            return None

    def start_upload(self):
        title = self.title_var.get()
        desc = self._get_desc_text_value()

        sc = self.steamcmd_path.get()
        content = self.mod_path.get()
        preview = self.preview_path.get()
        user = self.username_var.get().strip()
        pwd = self.password_var.get()
        use_cached = self.use_cached_creds_var.get()

        validation_error = self._get_upload_preflight().validate_inputs(
            title=title,
            description=desc,
            steamcmd_path=sc,
            content_path=content,
            preview_path=preview,
            username=user,
            use_cached_creds=use_cached,
            title_limit=STEAM_TITLE_LIMIT,
            description_limit=STEAM_DESC_LIMIT,
        )
        if validation_error:
            messagebox.showerror(validation_error[0], validation_error[1])
            return

        inventory = self._build_mod_inventory(content)
        findings = self._collect_mod_findings(content, inventory=inventory)
        plan = self._build_publish_plan(content, preview, use_cached, findings, inventory)

        if hasattr(self, "readiness_tree"):
            publish_ok, selected_fixups = self._confirm_publish_review(plan, findings)
        else:
            publish_ok = self._confirm_upload_plan(content, preview, use_cached)
            selected_fixups = []
        if not publish_ok:
            return

        if selected_fixups:
            findings = self._apply_publish_fixups(findings, selected_fixups)
            inventory = self.current_inventory or self._build_mod_inventory(content)

        self.save_config()
        self.save_current_project_state(quiet=True)
        
        # Create VDF
        try:
            appid = self.games[self.game_var.get()]["appid"]
            vis = self._visibility_code()
            vdf_path = self._get_upload_preflight().write_upload_vdf(
                base_dir=self.base_dir,
                appid=appid,
                publishedfileid=self.item_id_var.get(),
                contentfolder=content,
                previewfile=preview,
                visibility=vis,
                title=self.title_var.get(),
                description=desc,
                changenote=self.note_var.get(),
                build_upload_vdf_content=self._build_upload_vdf_content,
            )
            self.log(f"Generated VDF at {vdf_path}")
            
        except Exception as e:
            self.log(f"Error creating VDF: {e}")
            return

        # Run SteamCMD
        # We use a separate thread to not freeze UI, but we might need a new console for 2FA
        self.pending_publish_signature = self._fingerprint_inventory(inventory)
        self.pending_publish_inventory = self._build_inventory_snapshot(inventory)
        self._set_busy("Upload", True)
        threading.Thread(target=self.run_steamcmd, args=(sc, user, pwd, vdf_path), daemon=True).start()

    def run_steamcmd(self, exe, user, pwd, vdf):
        self.log("Starting SteamCMD...")
        
        use_cached = self.use_cached_creds_var.get()
        guard_code = self.steam_guard_var.get()
        if use_cached:
            if user:
                self.log(f"Attempting login using cached credentials for '{user}'...")
            else:
                self.log("Attempting login using cached credentials (no username provided)...")
        
        try:
            self.steamcmd_process, _cmd = self._get_workshop_backend().launch_steamcmd(
                exe=exe,
                user=user,
                pwd=pwd,
                vdf=vdf,
                use_cached=use_cached,
                guard_code=guard_code,
                is_windows=IS_WINDOWS,
            )
            self.steamcmd_process.wait()
            p = self.steamcmd_process
            self.steamcmd_process = None
            
            if p.returncode == 0:
                self.log("SteamCMD finished successfully.")
                updated_item_id = self.update_item_id_from_vdf(vdf)
                if updated_item_id:
                    self.item_id_var.set(updated_item_id)
                uploaded_item_id = updated_item_id or self.item_id_var.get().strip()
                self.current_project_data.update({
                    "last_upload_signature": self.pending_publish_signature,
                    "last_upload_inventory": self.pending_publish_inventory or {},
                    "last_upload_at": datetime.now(timezone.utc).isoformat(),
                    "last_uploaded_item_id": uploaded_item_id,
                    "item_id": uploaded_item_id or self.item_id_var.get(),
                })
                self._update_project_status(self.current_inventory)
                self.save_current_project_state(quiet=True)
                
                # Apply Tags if present
                if self.tags_var.get().strip():
                    self.update_workshop_tags(item_id_override=updated_item_id)
                
                self.root.after(0, self.refresh_current_project_readiness)
                self.root.after(0, lambda: messagebox.showinfo("Success", "SteamCMD finished.\nProject state and publish snapshot were updated."))
            else:
                self.log(f"SteamCMD exited with code {p.returncode}")
                
                analysis = self.analyze_last_upload_log()
                msg = f"SteamCMD encountered an error (Code {p.returncode})."
                
                if use_cached:
                    msg = "SteamCMD failed to login using cached credentials.\n\nPlease ensure you are logged into SteamCMD manually first, or use the QR Login / Manual boxes."
                elif analysis:
                    msg += f"\n\nPossible Errors found in log:\n{analysis}"
                
                def show_err():
                    if messagebox.askyesno("Upload Error", f"{msg}\n\nOpen logs to investigate?"):
                        self.show_steam_logs()
                self.root.after(0, show_err)
                
        except Exception as e:
            self.log(f"Execution Error: {e}")
        finally:
            self.pending_publish_signature = None
            self.pending_publish_inventory = None
            self._set_busy("Upload", False)

    def _on_manage_selection(self, _event=None):
        self.use_selected_item_id_for_upload(switch_to_upload=False, quiet=True)

    def use_selected_item_id_for_upload(self, switch_to_upload=True, quiet=False):
        selected = self.tree.selection()
        if not selected:
            if not quiet:
                messagebox.showinfo("Info", "Select a Workshop item first.")
            return False

        values = self.tree.item(selected[0]).get("values", [])
        if len(values) < 2:
            return False

        title = str(values[0])
        item_id = str(values[1])
        self.item_id_var.set(item_id)

        if switch_to_upload and getattr(self, "notebook", None) is not None:
            self.notebook.select(self.upload_tab)

        self.save_current_project_state(quiet=True)

        if not quiet:
            self.log(f"Project paired to Workshop ID {item_id}: {title}")
        return True

    def _resolve_vanity_to_steamid(self, vanity, api_key):
        return self._get_steam_service().resolve_vanity_to_steamid(
            vanity,
            api_key,
            retry_kwargs={
                "attempts": REQUEST_RETRY_ATTEMPTS,
                "backoff": REQUEST_BACKOFF_SECONDS,
            },
        )

    def resolve_steam_id(self, identity_input, api_key):
        return self._get_steam_service().resolve_steam_id(
            identity_input,
            api_key,
            retry_kwargs={
                "attempts": REQUEST_RETRY_ATTEMPTS,
                "backoff": REQUEST_BACKOFF_SECONDS,
            },
        )

    def _extract_loginusers_accounts(self, vdf_path):
        return self._get_steam_service().extract_loginusers_accounts(vdf_path)

    def detect_local_steam_identity(self):
        return self._get_steam_service().detect_local_steam_identity(
            steamcmd_exe=self.steamcmd_path.get().strip(),
            base_dir=self.base_dir,
        )

    def use_local_steam_identity(self):
        account = self.detect_local_steam_identity()
        if not account:
            messagebox.showerror("Not Found", "Could not auto-detect a local Steam login.\nEnter SteamID64 or profile URL manually.")
            return

        self.manage_identity_var.set(account["steamid"])
        if not self.username_var.get().strip() and account.get("account_name"):
            self.username_var.set(account["account_name"])

        display_name = account.get("persona_name") or account.get("account_name") or account["steamid"]
        self.log(f"Detected Steam login: {display_name} ({account['steamid']})")

    def refresh_workshop_items(self):
        if not self.api_key_var.get():
            messagebox.showerror("Error", "Steam Web API Key is required for this feature.")
            return

        identity_input = self.manage_identity_var.get().strip()
        if not identity_input:
            detected = self.detect_local_steam_identity()
            if detected:
                identity_input = detected["steamid"]
                self.manage_identity_var.set(identity_input)
                self.log(f"Auto-detected SteamID64 from local login: {identity_input}")

        if not identity_input:
            messagebox.showerror("Error", "Enter SteamID64/Profile URL/Vanity in Manage tab, or use 'USE CURRENT STEAM LOGIN'.")
            return

        self.log("Fetching workshop items...")
        self.library_status_var.set("Loading Workshop library...")
        self._set_busy("Refresh", True)
        threading.Thread(target=self._refresh_worker, args=(identity_input,), daemon=True).start()

    def _refresh_worker(self, identity_input):
        try:
            api_key = self.api_key_var.get()
            appid = self.games[self.game_var.get()]["appid"]
            steam_id, items = self._get_workshop_backend().query_workshop_items(
                api_key=api_key,
                identity_input=identity_input,
                appid=appid,
                resolve_steam_id=self.resolve_steam_id,
            )

            if not steam_id:
                self.root.after(0, lambda: self.log("Error: Could not resolve owner. Use SteamID64, profile URL, vanity URL, or 'USE CURRENT STEAM LOGIN'."))
                return

            self.root.after(0, lambda: self.manage_identity_var.set(steam_id))
            
            self.root.after(0, lambda: self.tree.delete(*self.tree.get_children()))
            
            for item in items:
                self.root.after(
                    0,
                    lambda i=item: self.tree.insert("", "end", values=(i["title"], i["publishedfileid"], i["visibility_label"], i["updated_label"]))
                )
            self.root.after(0, lambda: self.library_status_var.set(f"Loaded {len(items)} Workshop items for {steam_id}."))

        except Exception as e:
            self.root.after(0, lambda: self.library_status_var.set("Workshop library load failed."))
            self.root.after(0, lambda: self.log(f"API Error: {self._friendly_api_error(e)}"))
        finally:
            self._set_busy("Refresh", False)

    def update_workshop_tags(self, item_id_override=None):
        """Uses the Steam Web API to set tags on the workshop item."""
        api_key = self.api_key_var.get()
        item_id = item_id_override or self.item_id_var.get()
        tags_str = self.tags_var.get()
        change_note = self.note_var.get()
        
        if not item_id or item_id == "0" or not tags_str:
            return
            
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]
        if not tags: return
        
        self.log(f"Updating Workshop tags: {', '.join(tags)}...")
        
        def _worker():
            try:
                result = self._get_workshop_backend().update_workshop_tags(
                    api_key=api_key,
                    item_id=item_id,
                    appid=self.games[self.game_var.get()]["appid"],
                    tags=tags,
                    change_note=change_note,
                    steamworks_updater=self._get_steamworks_tag_updater(),
                    base_dir=self.base_dir,
                    create_appid_file=self.experimental_native_appid_var.get(),
                )
                if result.get("method") == "steamworks":
                    self.log("Workshop tags updated successfully via Steamworks.")
                    if result.get("needs_legal_agreement"):
                        self.log("Steamworks reported that a Workshop legal agreement may need acceptance.")
                else:
                    if result.get("native_error"):
                        self.log(f"Steamworks tag update failed; falling back to Web API: {result['native_error']}")
                    self.log("Workshop tags updated successfully via Web API.")
            except Exception as e:
                self.log(f"Tag Update Error: {self._friendly_api_error(e)}")
                
        threading.Thread(target=_worker, daemon=True).start()

    def prepare_update(self):
        selected = self.tree.selection()
        if not selected: return
        
        item_id = self.tree.item(selected[0])['values'][1]
        self.use_selected_item_id_for_upload(switch_to_upload=False, quiet=True)
        self.log(f"Fetching details for item {item_id}...")
        self._set_busy("Prepare Update", True)
        threading.Thread(target=self._prepare_update_worker, args=(item_id,), daemon=True).start()

    def _prepare_update_worker(self, item_id):
        try:
            api_key = self.api_key_var.get()
            details = self._get_workshop_backend().fetch_workshop_item_details(api_key=api_key, item_id=item_id)
            if not details:
                self.root.after(0, lambda: self.log(f"Could not fetch details for {item_id}"))
                return

            preview_url = details.get("preview_url")
            preview_local_path = ""
            if preview_url:
                preview_bytes = self._get_workshop_backend().download_preview_bytes(preview_url)
                if preview_bytes:
                    preview_local_path = os.path.join(self.temp_dir, f"{item_id}.jpg")
                    with open(preview_local_path, 'wb') as f:
                        f.write(preview_bytes)
            
            vis_map = {0: "0 (Public)", 1: "1 (Friends)", 2: "2 (Private)"}
            vis_str = vis_map.get(details.get("visibility"), "0 (Public)")

            def do_populate():
                self.item_id_var.set(details.get("publishedfileid", "0"))
                self.title_var.set(details.get("title", ""))
                self._set_desc_text_value(details.get("description", ""))
                self.preview_path.set(preview_local_path)
                self.visibility_var.set(vis_str)
                self.save_current_project_state(quiet=True)
            
            self.root.after(0, do_populate)
        except Exception as e:
            self.root.after(0, lambda: self.log(f"API Error: {self._friendly_api_error(e)}"))
        finally:
            self._set_busy("Prepare Update", False)

    def analyze_last_upload_log(self):
        sc_exe = self.steamcmd_path.get()
        if not sc_exe: return None
        appid = self.games[self.game_var.get()]["appid"]
        return self._get_workshop_backend().analyze_last_upload_log(sc_exe, appid)

    def show_steam_logs(self):
        sc_exe = self.steamcmd_path.get()
        if not sc_exe:
            messagebox.showerror("Error", "SteamCMD path not set.")
            return
            
        appid = self.games[self.game_var.get()]["appid"]
        logs = self._get_workshop_backend().get_log_paths(sc_exe, appid)
        
        win = tk.Toplevel(self.root)
        win.title("SteamCMD Logs")
        win.geometry("900x600")
        win.configure(bg="#1a1a1a")
        
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=5, pady=5)
        
        for name, path in logs:
            f = ttk.Frame(nb)
            nb.add(f, text=name)
            
            st = tk.Text(f, bg="#050505", fg="#d4d4d4", font=("Consolas", 9))
            st.pack(fill="both", expand=True)
            
            if os.path.exists(path):
                try:
                    with open(path, 'r', errors='ignore') as log_file:
                        content = log_file.read()
                        st.insert("end", content)
                        
                        st.tag_config("error", foreground="#ff5555", background="#220000")
                        for keyword in ["error", "failed"]:
                            start = "1.0"
                            while True:
                                pos = st.search(keyword, start, stopindex="end", nocase=True)
                                if not pos: break
                                end = f"{pos} lineend"
                                st.tag_add("error", pos, end)
                                start = end
                        st.see("end")
                except Exception as e:
                    st.insert("end", f"Error reading file: {e}")
            else:
                st.insert("end", f"Log file not found at:\n{path}\n\nThis log is usually created after an upload attempt.")

if __name__ == "__main__":
    root = tk.Tk()
    app = WorkshopUploader(root)
    root.mainloop()
