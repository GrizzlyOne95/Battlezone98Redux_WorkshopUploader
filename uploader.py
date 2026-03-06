import os
import sys
import json
import configparser
import subprocess
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ctypes
import re
import requests
import zipfile
import io
import time
from datetime import datetime

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    keyring = None
    HAS_KEYRING = False

# Platform check
IS_WINDOWS = sys.platform == "win32"

# --- CONFIGURATION ---
CONFIG_FILE = "uploader_config.json"
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
        self.root.geometry("1000x800")
        
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
            self.resource_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            self.resource_dir = self.base_dir
            
        self.profiles_dir = os.path.join(self.base_dir, "profiles")
        os.makedirs(self.profiles_dir, exist_ok=True)
            
        self.temp_dir = os.path.join(self.base_dir, "temp_previews")
        os.makedirs(self.temp_dir, exist_ok=True)

        self.steamcmd_process = None

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
        self.preview_path = tk.StringVar()
        self.title_var = tk.StringVar()
        self.title_var.trace_add("write", self._update_title_counter)
        self.desc_var = tk.StringVar()
        self.note_var = tk.StringVar(value="Initial Release")
        self.tags_var = tk.StringVar()
        self.visibility_var = tk.StringVar(value="0") # 0=Public, 1=Friends, 2=Private
        self.item_id_var = tk.StringVar(value="0")
        self.item_id_var.trace_add("write", self._update_upload_mode_indicator)
        
        self.username_var = tk.StringVar(value=self.config.get("username", ""))
        self.manage_identity_var = tk.StringVar(value=self.config.get("manage_identity", ""))
        self.password_var = tk.StringVar()
        self.steam_guard_var = tk.StringVar()
        self.use_cached_creds_var = tk.BooleanVar(value=self.config.get("use_cached_creds", False))
        self.use_cached_creds_var.trace_add("write", self._toggle_auth_fields)
        self.busy_status_var = tk.StringVar(value="STATUS: IDLE")
        self._active_operations = set()
        self._busy_lock = threading.Lock()
        self._warned_no_keyring = False
        
        self.qr_session_id = None
        self.qr_poll_timer = None
        
        self.watch_mode_var = tk.BooleanVar(value=False)
        self.watch_thread = None
        self.last_scan_time = 0
        
        self.setup_styles()
        self.setup_ui()

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
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return json.load(f)
            except Exception: pass
        return {}

    def save_config(self):
        cfg = {
            "steamcmd_path": self.steamcmd_path.get(),
            "last_game": self.game_var.get(),
            "username": self.username_var.get(),
            "manage_identity": self.manage_identity_var.get(),
            "use_cached_creds": self.use_cached_creds_var.get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f: json.dump(cfg, f, indent=4)
        except Exception: pass
        self._save_api_key_to_secure_store()

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
        main_font = (self.current_font, 10)
        bold_font = (self.current_font, 11, "bold")
        
        style.configure(".", background=c["bg"], foreground=c["fg"], font=main_font, bordercolor=c["dark_highlight"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#1a1a1a", foreground=c["fg"], padding=[10, 2])
        style.map("TNotebook.Tab", background=[("selected", c["dark_highlight"])], foreground=[("selected", c["highlight"])])
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["highlight"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["highlight"], font=bold_font)
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
        # Main Container
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill="both", expand=True)

        # --- TABS ---
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True, pady=10)

        self.upload_tab = ttk.Frame(self.notebook)
        self.manage_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.upload_tab, text=" UPLOAD ")
        self.notebook.add(self.manage_tab, text=" MANAGE ")

        self.setup_upload_tab(self.upload_tab)
        self.setup_manage_tab(self.manage_tab)

    def setup_upload_tab(self, parent_tab):
        
        # --- HEADER ---
        header = ttk.Frame(parent_tab)
        header.pack(fill="x", pady=(0, 20))
        ttk.Label(header, text="WORKSHOP UPLOADER", font=(self.current_font, 20, "bold"), foreground=self.colors["highlight"]).pack(side="left")
        
        # Game Selector
        self.game_combo = ttk.Combobox(header, textvariable=self.game_var, values=list(self.games.keys()), state="readonly", width=10)
        self.game_combo.pack(side="right")
        ttk.Label(header, text="Target Game:").pack(side="right", padx=10)

        # --- CONFIGURATION ---
        cfg_frame = ttk.LabelFrame(parent_tab, text=" SYSTEM CONFIG ", padding=10)
        cfg_frame.pack(fill="x", pady=5)
        
        # SteamCMD Path
        ttk.Label(cfg_frame, text="SteamCMD Path:").grid(row=0, column=0, sticky="w")
        ttk.Entry(cfg_frame, textvariable=self.steamcmd_path).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(cfg_frame, text="BROWSE", command=self.browse_steamcmd).grid(row=0, column=2)
        ttk.Button(cfg_frame, text="AUTO-DOWNLOAD", command=self.download_steamcmd).grid(row=0, column=3, padx=5)
        
        # Credentials
        ttk.Label(cfg_frame, text="Steam Username:").grid(row=1, column=0, sticky="w", pady=5)
        self.user_entry = ttk.Entry(cfg_frame, textvariable=self.username_var)
        self.user_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        
        ttk.Label(cfg_frame, text="Password:").grid(row=1, column=2, sticky="e", pady=5)
        self.pwd_entry = ttk.Entry(cfg_frame, textvariable=self.password_var, show="*")
        self.pwd_entry.grid(row=1, column=3, sticky="ew", padx=5)
        
        ttk.Label(cfg_frame, text="2FA Code:").grid(row=1, column=4, sticky="e", pady=5)
        self.guard_entry = ttk.Entry(cfg_frame, textvariable=self.steam_guard_var, width=10)
        self.guard_entry.grid(row=1, column=5, sticky="w", padx=5)
        
        # QR & Cached Creds
        auth_opts = ttk.Frame(cfg_frame)
        auth_opts.grid(row=2, column=1, columnspan=2, sticky="w", pady=5)
        
        self.qr_btn = ttk.Button(auth_opts, text="LOGIN WITH QR", command=self.start_qr_login)
        self.qr_btn.pack(side="left", padx=(0, 10))
        ToolTip(self.qr_btn, "Login without a password by scanning a QR code with your Steam Mobile App.")
        
        cached_cb = ttk.Checkbutton(auth_opts, text="USE CACHED CREDENTIALS", variable=self.use_cached_creds_var)
        cached_cb.pack(side="left")
        ToolTip(cached_cb, "If checked, SteamCMD will attempt to use existing login session.\nErrors if you are not already signed in.")

        # API Key
        ttk.Label(cfg_frame, text="Steam Web API Key:").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(cfg_frame, textvariable=self.api_key_var, show="*").grid(row=3, column=1, sticky="ew", padx=5)
        api_help = ttk.Button(cfg_frame, text="?", command=self.open_api_key_link, width=3)
        api_help.grid(row=3, column=2, padx=5)
        ToolTip(api_help, "Needed for the 'Manage' tab.\nGet one from steamcommunity.com/dev/apikey")
        
        cfg_frame.columnconfigure(1, weight=1)
        cfg_frame.columnconfigure(3, weight=1)

        # --- MOD DETAILS ---
        mod_frame = ttk.LabelFrame(parent_tab, text=" MOD DETAILS ", padding=10)
        mod_frame.pack(fill="both", expand=True, pady=10)
        
        # Profile Controls
        prof_frame = ttk.Frame(mod_frame)
        prof_frame.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        ttk.Button(prof_frame, text="LOAD PROFILE", command=self.load_profile).pack(side="left")
        ttk.Button(prof_frame, text="SAVE PROFILE", command=self.save_profile).pack(side="left", padx=5)
        self.upload_mode_label = ttk.Label(prof_frame, text="", foreground=self.colors["highlight"], font=(self.current_font, 10, "bold"))
        self.upload_mode_label.pack(side="right")
        self._update_upload_mode_indicator()
        
        # Content Path
        ttk.Label(mod_frame, text="Content Folder:").grid(row=1, column=0, sticky="w")
        ttk.Entry(mod_frame, textvariable=self.mod_path).grid(row=1, column=1, sticky="ew", padx=5)
        
        cf_btn_frame = ttk.Frame(mod_frame)
        cf_btn_frame.grid(row=1, column=2)
        ttk.Button(cf_btn_frame, text="BROWSE", command=self.browse_content).pack(side="left")
        ttk.Button(cf_btn_frame, text="ANALYZE", width=8, command=self.analyze_memory_usage).pack(side="left", padx=2)
        ttk.Button(cf_btn_frame, text="NEW...", width=6, command=self.open_template_wizard).pack(side="left")
        
        watch_cb = ttk.Checkbutton(cf_btn_frame, text="WATCH", variable=self.watch_mode_var, command=self.toggle_watch_mode)
        watch_cb.pack(side="left", padx=5)
        ToolTip(watch_cb, "Live monitoring of the content folder.\nAutomatically scans for errors when files change.")
        
        # Preview Image
        ttk.Label(mod_frame, text="Preview Image:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(mod_frame, textvariable=self.preview_path).grid(row=2, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(mod_frame, text="BROWSE", command=self.browse_preview).grid(row=2, column=2, pady=5)
        
        # Title
        ttk.Label(mod_frame, text="Title:").grid(row=3, column=0, sticky="w")
        ttk.Entry(mod_frame, textvariable=self.title_var).grid(row=3, column=1, columnspan=2, sticky="ew", padx=5)
        
        self.title_char_label = ttk.Label(mod_frame, text=f"0 / {STEAM_TITLE_LIMIT}")
        self.title_char_label.grid(row=3, column=3, sticky="w", padx=5)
        
        # Description
        ttk.Label(mod_frame, text="Description:").grid(row=4, column=0, sticky="nw", pady=5)
        self.desc_text = tk.Text(mod_frame, height=5, bg="#1a1a1a", fg=self.colors["accent"], insertbackground=self.colors["highlight"], font=("Consolas", 10))
        self.desc_text.grid(row=4, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        self.desc_text.bind("<KeyRelease>", self._update_desc_counter)
        
        self.desc_char_label = ttk.Label(mod_frame, text=f"0 / {STEAM_DESC_LIMIT}")
        self.desc_char_label.grid(row=4, column=3, sticky="nw", pady=5, padx=5)
        
        # Metadata Row
        meta_row = ttk.Frame(mod_frame)
        meta_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=5)
        
        ttk.Label(meta_row, text="Visibility:").pack(side="left")
        ttk.Combobox(meta_row, textvariable=self.visibility_var, values=["0 (Public)", "1 (Friends)", "2 (Private)"], state="readonly", width=15).pack(side="left", padx=5)
        
        ttk.Label(meta_row, text="Workshop ID (0=New):").pack(side="left", padx=(20, 5))
        ttk.Entry(meta_row, textvariable=self.item_id_var, width=15).pack(side="left", padx=5)
        reset_btn = ttk.Button(meta_row, text="CREATE NEW ITEM", command=self.set_create_mode)
        reset_btn.pack(side="left", padx=(2, 6))
        ToolTip(reset_btn, "Switches the uploader to create a new Workshop item (Workshop ID = 0).")
        
        link_btn = ttk.Button(meta_row, text="↗", width=3, command=self.open_workshop_page)
        link_btn.pack(side="left", padx=2)
        ToolTip(link_btn, "Open Workshop Page")
        
        ttk.Label(meta_row, text="Change Note:").pack(side="left", padx=(20, 5))
        ttk.Entry(meta_row, textvariable=self.note_var).pack(side="left", fill="x", expand=True, padx=5)
        
        # Tags Row (New)
        tags_row = ttk.Frame(mod_frame)
        tags_row.grid(row=6, column=0, columnspan=3, sticky="ew", pady=5)
        ttk.Label(tags_row, text="Tags (comma separated) [EXPERIMENTAL]:").pack(side="left")
        ttk.Entry(tags_row, textvariable=self.tags_var).pack(side="left", fill="x", expand=True, padx=5)
        ToolTip(tags_row, "EXPERIMENTAL: Uses Web API to update tags post-upload.\nCommon API keys may lack permissions.\nExamples: Map, Vehicle, Building, Weapon")
        
        mod_frame.columnconfigure(1, weight=1)

        # --- ACTIONS ---
        btn_frame = ttk.Frame(parent_tab)
        btn_frame.pack(fill="x", pady=10)
        
        self.log_box = tk.Text(parent_tab, height=8, state="disabled", bg="#050505", fg=self.colors["fg"], font=("Consolas", 9))
        self.log_box.pack(fill="x", pady=(0, 10))
        
        self.upload_btn = ttk.Button(btn_frame, text="UPLOAD TO STEAM WORKSHOP", command=self.start_upload, style="Success.TButton")
        self.upload_btn.pack(side="left", fill="x", expand=True, ipady=5)
        self.logs_btn = ttk.Button(btn_frame, text="LOGS", width=10, command=self.show_steam_logs)
        self.logs_btn.pack(side="right", fill="y", padx=(5,0))
        self.busy_status_label = ttk.Label(btn_frame, textvariable=self.busy_status_var, foreground="#ffff44")
        self.busy_status_label.pack(side="right", padx=(0, 10))

    def setup_manage_tab(self, parent_tab):
        # --- CONTROLS ---
        ctrl_frame = ttk.Frame(parent_tab, padding=10)
        ctrl_frame.pack(fill="x")

        self.refresh_btn = ttk.Button(ctrl_frame, text="Refresh List", command=self.refresh_workshop_items)
        self.refresh_btn.pack(side="left")
        self.manage_set_target_btn = ttk.Button(ctrl_frame, text="Use Selected ID in Upload", command=self.use_selected_item_id_for_upload)
        self.manage_set_target_btn.pack(side="left", padx=(10, 0))
        ToolTip(self.manage_set_target_btn, "Copies the selected Workshop ID into the Upload tab and switches to update mode.")
        
        self.manage_update_btn = ttk.Button(ctrl_frame, text="Prepare for Update", command=self.prepare_update)
        self.manage_update_btn.pack(side="left", padx=10)
        ToolTip(self.manage_update_btn, "Populates the Upload tab with the selected item's data.\nYou will then need to select the content folder and click Upload.")
        
        info_label = ttk.Label(ctrl_frame, text="Requires API Key.", foreground="#ffff44")
        info_label.pack(side="right")

        identity_frame = ttk.Frame(parent_tab, padding=(10, 0, 10, 10))
        identity_frame.pack(fill="x")

        ttk.Label(identity_frame, text="Workshop Owner (SteamID64 / Profile URL / Vanity):").pack(side="left")
        self.manage_owner_entry = ttk.Entry(identity_frame, textvariable=self.manage_identity_var)
        self.manage_owner_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.manage_detect_btn = ttk.Button(identity_frame, text="USE CURRENT STEAM LOGIN", command=self.use_local_steam_identity)
        self.manage_detect_btn.pack(side="left")
        ToolTip(self.manage_detect_btn, "Auto-detects your most recent Steam account and fills the owner as SteamID64.")

        # --- TREEVIEW ---
        tree_frame = ttk.Frame(parent_tab)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(tree_frame, columns=("Title", "ID", "Visibility", "Updated"), show="headings")
        self.tree.heading("Title", text="Title")
        self.tree.heading("ID", text="Workshop ID")
        self.tree.heading("Visibility", text="Visibility")
        self.tree.heading("Updated", text="Last Updated")

        self.tree.column("Title", width=400)
        self.tree.column("ID", width=150, anchor="center")
        self.tree.column("Visibility", width=100, anchor="center")
        self.tree.column("Updated", width=150, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_manage_selection)
        self.tree.bind("<Double-1>", lambda e: self.prepare_update())

    def _update_title_counter(self, *args):
        count = len(self.title_var.get())
        self.title_char_label.config(text=f"{count} / {STEAM_TITLE_LIMIT}")
        if count > STEAM_TITLE_LIMIT:
            self.title_char_label.config(foreground="red")
        else:
            self.title_char_label.config(foreground=self.colors["fg"])

    def _update_desc_counter(self, *args):
        count = len(self.desc_text.get("1.0", "end-1c"))
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

    def set_create_mode(self):
        self.item_id_var.set("0")
        self.log("Upload mode set to CREATE NEW ITEM.")

    def _friendly_api_error(self, error=None, response=None):
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

    def _request_with_retry(self, method, url, operation_name="request", timeout=10, attempts=REQUEST_RETRY_ATTEMPTS, backoff=REQUEST_BACKOFF_SECONDS, **kwargs):
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                response = requests.request(method=method, url=url, timeout=timeout, **kwargs)
                if response.status_code in (429,) or response.status_code >= 500:
                    if attempt < attempts:
                        self.log(f"{operation_name} failed ({self._friendly_api_error(response=response)}). Retrying ({attempt}/{attempts})...")
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
                self.log(f"{operation_name} failed ({self._friendly_api_error(e)}). Retrying ({attempt}/{attempts})...")
                time.sleep(backoff * (2 ** (attempt - 1)))

        if last_error:
            raise last_error
        raise RuntimeError(f"{operation_name} failed.")

    def _vdf_escape(self, value):
        text = str(value if value is not None else "")
        text = text.replace("\\", "\\\\")
        text = text.replace("\"", "\\\"")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\n", "\\n")
        return text

    def _build_upload_vdf_content(self, appid, publishedfileid, contentfolder, previewfile, visibility, title, description, changenote):
        values = {
            "appid": self._vdf_escape(appid),
            "publishedfileid": self._vdf_escape(publishedfileid),
            "contentfolder": self._vdf_escape(os.path.abspath(contentfolder)),
            "previewfile": self._vdf_escape(os.path.abspath(previewfile)),
            "visibility": self._vdf_escape(visibility),
            "title": self._vdf_escape(title),
            "description": self._vdf_escape(description),
            "changenote": self._vdf_escape(changenote),
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

    def _confirm_upload_plan(self, content, preview, use_cached_creds):
        item_id = self.item_id_var.get().strip()
        mode = f"UPDATE ({item_id})" if item_id.isdigit() and item_id != "0" else "CREATE NEW"
        auth_mode = "Cached credentials" if use_cached_creds else f"Manual login ({self.username_var.get().strip()})"
        summary_lines = [
            "Upload Plan",
            f"- Mode: {mode}",
            f"- Game: {self.game_var.get()} (AppID {self.games[self.game_var.get()]['appid']})",
            f"- Workshop ID: {item_id or '0'}",
            f"- Visibility: {self.visibility_var.get()}",
            f"- Title: {self.title_var.get()}",
            f"- Content Folder: {os.path.abspath(content)}",
            f"- Preview Image: {os.path.abspath(preview)}",
            f"- Auth: {auth_mode}",
            f"- Manage Owner Field: {self.manage_identity_var.get().strip() or '(empty)'}",
            f"- Change Note: {self.note_var.get().strip() or '(empty)'}",
        ]
        prompt = "\n".join(summary_lines) + "\n\nProceed with upload?"
        return messagebox.askyesno("Confirm Upload Plan", prompt)

    def _tokenize_vdf(self, text):
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

            # Support unquoted tokens used in some VDF variants.
            start = i
            while i < length and (not text[i].isspace()) and text[i] not in "{}":
                i += 1
            tokens.append(("STRING", text[start:i]))

        return tokens

    def _parse_vdf_tokens(self, tokens, start_index=0, expect_closing=False):
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
                value, i = self._parse_vdf_tokens(tokens, i + 1, expect_closing=True)
            else:
                value = next_token[1]
                i += 1
            data[key] = value

        if expect_closing:
            raise ValueError("Missing closing brace in VDF.")
        return data, i

    def _parse_vdf_text(self, text):
        tokens = self._tokenize_vdf(text)
        parsed, _ = self._parse_vdf_tokens(tokens)
        return parsed

    def _dict_get_ci(self, dct, key, default=""):
        if not isinstance(dct, dict):
            return default
        for k, v in dct.items():
            if str(k).lower() == key.lower():
                return v
        return default

    def open_api_key_link(self):
        webbrowser.open("https://steamcommunity.com/dev/apikey")

    def resize_preview_image(self, image_path):
        try:
            img = Image.open(image_path)
            if img.mode != 'RGB': img = img.convert('RGB')
            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            out_path = os.path.join(self.temp_dir, os.path.basename(image_path) + "_resized.jpg")
            for quality in range(90, 20, -5):
                img.save(out_path, "jpeg", quality=quality, optimize=True)
                if os.path.getsize(out_path) < 1024 * 1024: return out_path
        except Exception as e: self.log(f"Error resizing image: {e}")
        return None

    def save_profile(self):
        f = filedialog.asksaveasfilename(initialdir=self.profiles_dir, defaultextension=".json", filetypes=[("JSON Profile", "*.json")])
        if not f: return
        
        data = {
            "mod_path": self.mod_path.get(),
            "preview_path": self.preview_path.get(),
            "title": self.title_var.get(),
            "description": self.desc_text.get("1.0", "end-1c"),
            "visibility": self.visibility_var.get(),
            "item_id": self.item_id_var.get(),
            "change_note": self.note_var.get(),
            "tags": self.tags_var.get()
        }
        try:
            with open(f, 'w') as outfile:
                json.dump(data, outfile, indent=4)
            self.log(f"Profile saved: {os.path.basename(f)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def load_profile(self):
        f = filedialog.askopenfilename(initialdir=self.profiles_dir, filetypes=[("JSON Profile", "*.json")])
        if not f: return
        
        try:
            with open(f, 'r') as infile:
                data = json.load(infile)
                self.mod_path.set(data.get("mod_path", ""))
                self.preview_path.set(data.get("preview_path", ""))
                self.title_var.set(data.get("title", ""))
                self.desc_text.delete("1.0", "end")
                self.desc_text.insert("1.0", data.get("description", ""))
                self.visibility_var.set(data.get("visibility", "0 (Public)"))
                self.item_id_var.set(data.get("item_id", "0"))
                self.note_var.set(data.get("change_note", ""))
                self.tags_var.set(data.get("tags", ""))
            self.log(f"Profile loaded: {os.path.basename(f)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load profile: {e}")

    def log(self, msg):
        self.root.after(0, lambda: self._log_impl(msg))

    def _log_impl(self, msg):
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
                url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
                r = self._request_with_retry("GET", url, operation_name="Download SteamCMD", timeout=30)
                
                target_dir = os.path.join(self.base_dir, "steamcmd")
                os.makedirs(target_dir, exist_ok=True)
                
                z = zipfile.ZipFile(io.BytesIO(r.content))
                z.extractall(target_dir)
                
                exe_path = os.path.join(target_dir, "steamcmd.exe")
                if os.path.exists(exe_path):
                    self.root.after(0, lambda: self.steamcmd_path.set(exe_path))
                    self.log("SteamCMD successfully downloaded and extracted.")
                    self.root.after(0, lambda: messagebox.showinfo("Success", "SteamCMD downloaded and path set automatically."))
                else:
                    self.log("Error: steamcmd.exe not found after extraction.")
                    
            except Exception as e:
                self.log(f"Download Error: {e}")
                self.root.after(0, lambda: messagebox.showerror("Download Error", f"Failed to download SteamCMD: {e}"))
                
        threading.Thread(target=_worker, daemon=True).start()

    def open_template_wizard(self):
        TemplateWizard(self.root, self.colors, on_success=lambda p: self.mod_path.set(p))

    def toggle_watch_mode(self):
        if self.watch_mode_var.get():
            self.log("Watch Mode enabled.")
            if not self.watch_thread or not self.watch_thread.is_alive():
                self.watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
                self.watch_thread.start()
        else:
            self.log("Watch Mode disabled.")

    def _watch_loop(self):
        import time
        while self.watch_mode_var.get():
            mod_dir = self.mod_path.get()
            if mod_dir and os.path.exists(mod_dir):
                try:
                    current_max_time = 0
                    for root, _, files in os.walk(mod_dir):
                        for f in files:
                            t = os.path.getmtime(os.path.join(root, f))
                            if t > current_max_time: current_max_time = t
                    
                    if self.last_scan_time == 0:
                        self.last_scan_time = current_max_time
                    elif current_max_time > self.last_scan_time:
                        self.last_scan_time = current_max_time
                        self.log("Change detected! Scanning...")
                        issues = self.scan_mod_safety(mod_dir)
                        issues.extend(self.scan_asset_references(mod_dir))
                        if issues:
                            self.log(f"Watch Alert: {len(issues)} issues found.")
                        else:
                            self.log("Watch: Files verified.")
                except Exception as e: pass
            time.sleep(3)

    def browse_content(self):
        d = filedialog.askdirectory()
        if d: self.mod_path.set(d)

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
                        if new_path: self.preview_path.set(new_path)
            except Exception as e: self.log(f"Image size check failed: {e}")

    def start_qr_login(self):
        """Starts the Steam QR Login process."""
        self.log("Initializing QR login...")
        try:
            # Step 1: Begin Auth Session
            url = "https://api.steampowered.com/IAuthenticationService/BeginAuthSessionViaQR/v1/"
            # We use a generic device name
            data = {
                "device_friendly_name": f"BZR Uploader ({os.environ.get('COMPUTERNAME', 'Windows')})",
                "platform_type": 1 # k_EAuthTokenPlatformType_SteamClient
            }
            r = requests.post(url, data=data, timeout=10)
            r.raise_for_status()
            res = r.json().get("response", {})
            
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
        
        # Use external API for QR generation
        qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={requests.utils.quote(challenge_url)}"
        
        def load_qr():
            try:
                r = requests.get(qr_api_url, timeout=10)
                if r.ok:
                    from io import BytesIO
                    if HAS_PIL:
                        img = Image.open(BytesIO(r.content))
                        from PIL import ImageTk
                        self.qr_img = ImageTk.PhotoImage(img)
                        self.qr_label.config(image=self.qr_img, text="")
                    else:
                        self.qr_label.config(text="QR Loaded (PIL missing)\nScan the link manually?")
                        self.log("Warning: PIL missing, cannot display QR image in UI.")
            except Exception as e:
                self.qr_label.config(text=f"Failed to load QR\n{e}")

        threading.Thread(target=load_qr, daemon=True).start()
        
        ttk.Label(self.qr_win, text="1. Open Steam Mobile App\n2. Go to Steam Guard\n3. Select 'Scan a QR Code'", background="#1a1a1a", foreground="#d4d4d4", justify="left").pack(pady=10)
        
        cancel_btn = ttk.Button(self.qr_win, text="CANCEL", command=self.cancel_qr_login)
        cancel_btn.pack(pady=(10, 20))
        
        self.qr_win.protocol("WM_DELETE_WINDOW", self.cancel_qr_login)
        self.qr_win.transient(self.root)
        self.qr_win.grab_set()

    def poll_qr_status(self):
        if not self.qr_session_id: return
        
        try:
            url = "https://api.steampowered.com/IAuthenticationService/PollAuthSessionStatus/v1/"
            data = {"client_id": self.qr_session_id, "request_id": self.qr_session_id} 
            # Actually, the API says "client_id" and we need to check the status.
            
            r = requests.post(url, data=data, timeout=5)
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

    def analyze_memory_usage(self):
        mod_dir = self.mod_path.get()
        if not mod_dir or not os.path.exists(mod_dir):
            messagebox.showerror("Error", "Please select a valid content folder first.")
            return

        self.log("Analyzing memory footprint...")
        
        stats = {
            "disk_size": 0,
            "est_vram": 0,
            "counts": {"Texture": 0, "Model": 0, "Audio": 0, "Script": 0, "Other": 0}
        }

        non_dds_textures = []
        all_files = {} # name_lower: full_path
        
        def get_uncompressed_size(path):
            # 4 bytes per pixel (RGBA) + 33% for Mipmaps
            try:
                if HAS_PIL:
                    with Image.open(path) as img:
                        return (img.width * img.height * 4) * 1.33
            except Exception: pass
            # Fallback: File size * 5 (rough compression ratio estimate for PNG/JPG)
            return os.path.getsize(path) * 5

        for root, _, files in os.walk(mod_dir):
            for f in files:
                path = os.path.join(root, f)
                all_files[f.lower()] = path
                try:
                    size = os.path.getsize(path)
                    stats["disk_size"] += size
                    
                    ext = f.lower().split('.')[-1]
                    
                    if ext in ['png', 'tga', 'bmp', 'jpg', 'jpeg', 'tif', 'tiff']:
                        stats["counts"]["Texture"] += 1
                        stats["est_vram"] += get_uncompressed_size(path)
                        non_dds_textures.append(f)
                    elif ext in ['dds']:
                        stats["counts"]["Texture"] += 1
                        stats["est_vram"] += size 
                    elif ext in ['x', 'geo', 'xsi', '3ds']:
                        stats["counts"]["Model"] += 1
                        stats["est_vram"] += size * 3 # Rough estimate for vertex buffers
                    elif ext in ['wav', 'ogg']:
                        stats["counts"]["Audio"] += 1
                    elif ext in ['lua', 'odf', 'inf']:
                        stats["counts"]["Script"] += 1
                    else:
                        stats["counts"]["Other"] += 1
                        
                except Exception as e:
                    self.log(f"Skipped {f}: {e}")

        # --- ORPHAN FINDER ---
        self.log("Scanning for orphaned files...")
        referenced = set()
        # Add the main INI/MAP files as implicitly referenced
        for f in all_files:
            if f.endswith(('.ini', '.hg2', '.trn', '.mat', '.bzn', '.lgt')):
                referenced.add(f)

        asset_exts = ('.hg2', '.trn', '.mat', '.bzn', '.lgt', '.bmp', '.des', '.vxt', 
                      '.wav', '.ogg', '.tga', '.dds', '.x', '.geo', '.xsi', '.3ds', '.png', '.jpg')
        
        asset_ext_priority = {ext: i for i, ext in enumerate(asset_exts)}
        best_asset_for_basename = {}
        for f in all_files:
            base, ext = os.path.splitext(f)
            if ext in asset_ext_priority:
                curr_best = best_asset_for_basename.get(base)
                if curr_best is None or asset_ext_priority[ext] < asset_ext_priority[os.path.splitext(curr_best)[1]]:
                    best_asset_for_basename[base] = f

        quote_pattern = re.compile(r'["\']([^"\'\r\n]+)["\']')
        eq_pattern = re.compile(r'=\s*([\w\.\-]+)')

        for path in all_files.values():
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.odf', '.material', '.inf', '.lua', '.ini', '.txt'):
                try:
                    with open(path, 'r', errors='ignore') as f:
                        content = f.read()
                        # Find potential filenames in quotes or after =
                        potential = quote_pattern.findall(content)
                        potential.extend(eq_pattern.findall(content))
                        
                        for p in set(potential):
                            p_low = p.lower()
                            if p_low in all_files:
                                referenced.add(p_low)
                            elif p_low in best_asset_for_basename:
                                referenced.add(best_asset_for_basename[p_low])
                except Exception: pass

        orphans = [f for f in all_files if f not in referenced and not f.endswith('.ini')]
        
        disk_mb = stats["disk_size"] / (1024 * 1024)
        vram_mb = stats["est_vram"] / (1024 * 1024)
        
        report = (
            f"MEMORY ANALYSIS REPORT\n"
            f"----------------------\n"
            f"Total Disk Size: {disk_mb:.2f} MB\n"
            f"Est. Runtime Memory: {vram_mb:.2f} MB\n\n"
            f"Asset Breakdown:\n"
            f"  Textures: {stats['counts']['Texture']}\n"
            f"  Models: {stats['counts']['Model']}\n"
            f"  Audio: {stats['counts']['Audio']}\n"
            f"  Scripts: {stats['counts']['Script']}\n"
        )

        if non_dds_textures:
            report += f"\n[!] WARNING: {len(non_dds_textures)} non-DDS textures found.\n"
            report += "These will consume more VRAM than DDS (DXT) compressed files.\n"

        if orphans:
            report += f"\n[?] ORPHANS: {len(orphans)} files appear unused:\n"
            for o in orphans[:10]: report += f"  - {o}\n"
            if len(orphans) > 10: report += f"  ... and {len(orphans)-10} more.\n"
            report += "\n(Check carefully before deleting; scripts may use dynamic names.)"

        if vram_mb > 2000:
            report += f"\n\n[!] CRITICAL: Est. VRAM usage ({vram_mb:.0f}MB) is very high!\n"
            report += "Battlezone 98 Redux may crash on lower-end hardware."
        elif vram_mb > 1000:
            report += f"\n\n[!] WARNING: Est. VRAM usage ({vram_mb:.0f}MB) is high.\n"
            report += "Consider using DDS (DXT) for large textures."

        messagebox.showinfo("Memory Analysis", report)
        self.log(f"Analysis: Disk={disk_mb:.1f}MB, Est.Mem={vram_mb:.1f}MB, Orphans={len(orphans)}")

    def scan_mod_safety(self, mod_dir):
        allowed_headers = set()
        allowed_params = {}
        
        header_list_path = os.path.join(self.resource_dir, "odfHeaderList.txt")
        if os.path.exists(header_list_path):
            with open(header_list_path, 'r') as f:
                allowed_headers = {line.strip() for line in f if line.strip()}
        
        params_list_path = os.path.join(self.resource_dir, "bzrODFparams.txt")
        if os.path.exists(params_list_path):
            current_class = None
            with open(params_list_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('-') or line.startswith('//'): continue
                    
                    if line.startswith('[') and line.endswith(']'):
                        current_class = line[1:-1]
                        # Filter out garbage headers if any exist in the file
                        if re.match(r'^[A-Za-z0-9_]+$', current_class):
                            allowed_params[current_class] = set()
                        else:
                            current_class = None
                    elif current_class:
                        # Handle "paramName? -comment" -> "paramName"
                        # Also strip trailing '?' if present
                        parts = line.split()
                        if parts:
                            param = parts[0].rstrip('?')
                            allowed_params[current_class].add(param)

        if not allowed_headers:
            return []

        issues = []
        for root, _, files in os.walk(mod_dir):
            for file in files:
                if file.lower().endswith(".odf"):
                    path = os.path.join(root, file)
                    try:
                        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                            current_header = None
                            current_header_line = 0
                            found_params = set()

                            for i, line in enumerate(f):
                                line = line.split('//')[0].split('--')[0].strip() # Strip comments
                                if not line: continue
                                if line.startswith("//") or line.startswith("--"): continue
                                
                                if line.startswith('[') and line.endswith(']'):
                                    # Check previous header for missing params
                                    if current_header and current_header in allowed_params:
                                        missing = allowed_params[current_header] - found_params
                                        if missing:
                                            issues.append((path, "Missing Fields", f"[{current_header}] missing: {', '.join(missing)}", current_header_line))

                                    header = line[1:-1]
                                    current_header = header
                                    current_header_line = i + 1
                                    found_params = set()

                                    if header not in allowed_headers:
                                        issues.append((path, "Invalid Header", header, i+1))
                                
                                elif '=' in line and current_header:
                                    key = line.split('=')[0].strip()
                                    if current_header in allowed_params:
                                        if key not in allowed_params[current_header]:
                                            issues.append((path, "Unknown Field", f"[{current_header}] {key}", i+1))
                                        else:
                                            found_params.add(key)
                            
                            # Check last header
                            if current_header and current_header in allowed_params:
                                missing = allowed_params[current_header] - found_params
                                if missing:
                                    issues.append((path, "Missing Fields", f"[{current_header}] missing: {', '.join(missing)}", current_header_line))

                    except Exception as e:
                        self.log(f"Warning: Could not scan {file}: {e}")
        return issues

    def scan_asset_references(self, mod_dir):
        issues = []
        existing_files = set()
        files_to_process = []

        # Pre-compile regexes
        odf_pattern = re.compile(r'(geometryName|cockpitName|turretName)\s*=\s*"([^"]+)"', re.IGNORECASE)
        material_pattern = re.compile(r'texture\s+([^\s]+)', re.IGNORECASE)

        # Collect existing files and files to process in a single pass
        for root, _, files in os.walk(mod_dir):
            files_in_dir = []
            for f in files:
                f_lower = f.lower()
                existing_files.add(f_lower)
                # Only track files we actually need to parse
                if f_lower.endswith(".odf") or f_lower.endswith(".material"):
                    files_in_dir.append((f, f_lower))
            if files_in_dir:
                files_to_process.append((root, files_in_dir))

        # Process collected files
        for root, files in files_to_process:
            for file, file_lower in files:
                is_odf = file_lower.endswith(".odf")
                path = os.path.join(root, file)
                try:
                    # Add encoding='utf-8' per memory guidelines
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f):
                            # Optimize line parsing: skip split/strip if not needed
                            if '//' in line:
                                line = line.split('//')[0]
                            line = line.strip()
                            if not line:
                                continue
                            
                            if is_odf:
                                match = odf_pattern.search(line)
                                if match:
                                    asset = match.group(2).lower()
                                    if asset and asset not in existing_files:
                                        issues.append((path, "Missing Asset", f"Missing {match.group(1)}: {asset}", i+1))
                            else:  # is_material
                                match = material_pattern.search(line)
                                if match:
                                    asset = match.group(1).lower()
                                    if asset and asset not in existing_files:
                                        issues.append((path, "Missing Asset", f"Missing texture: {asset}", i+1))
                except Exception: pass
        return issues

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
        for path, issue_type, detail, line in issues:
            try: rel_path = os.path.relpath(path, self.mod_path.get())
            except Exception: rel_path = path
            item_id = tree.insert("", "end", values=(rel_path, issue_type, detail, line))
            issue_map[item_id] = path
            
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
        fixed_count = 0
        weapon_mask_re = re.compile(r'(weaponMask\s*=\s*)["\']?0+["\']?', re.IGNORECASE)
        missing_fields_re = re.compile(r'missing:\s*(.+)')

        for path, issue_type, detail, line_num in issues:
            try:
                # Fix 1: WeaponMask Crash
                if issue_type == "Crash Risk" and "weaponMask" in detail:
                    with open(path, 'r', encoding="utf-8", errors="ignore") as f: lines = f.readlines()
                    if line_num <= len(lines):
                        # Replace 00000 with 00001
                        lines[line_num-1] = weapon_mask_re.sub(r'\1"00001"', lines[line_num-1])
                        with open(path, 'w') as f: f.writelines(lines)
                        fixed_count += 1
                
                # Fix 2: Missing Fields
                elif issue_type == "Missing Fields":
                    # Detail format: "[Header] missing: key1, key2"
                    match = missing_fields_re.search(detail)
                    if match:
                        keys = [k.strip() for k in match.group(1).split(',')]
                        with open(path, 'a', encoding="utf-8") as f:
                            f.write(f"\n// Auto-fixed missing fields\n")
                            for k in keys:
                                f.write(f"{k} = 0\n")
                        fixed_count += 1
            except Exception as e:
                self.log(f"Quick Fix failed for {os.path.basename(path)}: {e}")
        return fixed_count

    def scan_trn_safety(self, mod_dir):
        le_issues = []
        dup_issues = []
        for root, _, files in os.walk(mod_dir):
            for file in files:
                if file.lower().endswith(".trn"):
                    path = os.path.join(root, file)
                    try:
                        with open(path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
                            text = f.read()
                        
                        if re.search(r'(?<!\r)\n', text) or re.search(r'\r(?!\n)', text):
                            le_issues.append(path)
                        
                        # Check for duplicate [Size] headers
                        if len(re.findall(r'^\s*\[Size\]', text, re.MULTILINE | re.IGNORECASE)) > 1:
                            dup_issues.append(path)
                            
                    except Exception as e:
                        self.log(f"Warning: Could not scan TRN {file}: {e}")
        return le_issues, dup_issues

    def scan_legacy_files(self, mod_dir):
        legacy_files = []
        for root, _, files in os.walk(mod_dir):
            for f in files:
                if f.lower().endswith(".map"):
                    legacy_files.append(os.path.join(root, f))
        return legacy_files

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
                with open(path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
                    content = f.read()
                
                # Normalize to CRLF
                content = content.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
                
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    f.write(content)
                count += 1
            except Exception as e:
                self.log(f"Error fixing {path}: {e}")
        return count

    def fix_trn_duplicates(self, files):
        count = 0
        for path in files:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                
                new_lines = []
                size_found = False
                skip_mode = False
                
                for line in lines:
                    # Strip comments for checking
                    clean = line.split('//')[0].split('--')[0].strip().lower()
                    
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
                    else:
                        if not skip_mode:
                            new_lines.append(line)
                            
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                count += 1
            except Exception as e:
                self.log(f"Error fixing {path}: {e}")
        return count

    def validate_content_structure(self, mod_dir):
        errors = []
        warnings = []
        
        try:
            files = os.listdir(mod_dir)
        except Exception as e:
            errors.append(f"Could not access content folder: {e}")
            return errors, warnings

        # Remove desktop.ini if present
        for f in files[:]:
            if f.lower() == "desktop.ini":
                try:
                    os.remove(os.path.join(mod_dir, f))
                    self.log(f"Removed hidden system file: {f}")
                    files.remove(f)
                except Exception as e:
                    self.log(f"Warning: Could not remove {f}: {e}")

        ini_files = [f for f in files if f.lower().endswith(".ini") and os.path.isfile(os.path.join(mod_dir, f))]
        
        if not ini_files:
            errors.append("Missing configuration (.ini) file in content root.")
            return errors, warnings
            
        target_ini = ini_files[0]
        ini_path = os.path.join(mod_dir, target_ini)
        
        config = configparser.ConfigParser()
        try:
            with open(ini_path, 'r', encoding='utf-8-sig') as f:
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
        files_lower = set(f.lower() for f in files)
        
        def check_ext(ext, required=True):
            if f"{base_name}{ext}".lower() not in files_lower:
                (errors if required else warnings).append(f"Missing {'essential' if required else 'optional'} file: {base_name}{ext}")

        if map_type in ["multiplayer", "instant_action"]:
            for ext in [".hg2", ".trn", ".mat", ".bzn", ".lgt"]: check_ext(ext)
            
            if map_type == "multiplayer":
                for ext in [".bmp", ".des", ".vxt"]: check_ext(ext, required=False)
                if "MULTIPLAYER" not in config:
                    errors.append(f"{target_ini} missing [MULTIPLAYER] section.")
                else:
                    for key in ["minplayers", "maxplayers", "gametype"]:
                        if key not in config["MULTIPLAYER"]: warnings.append(f"[MULTIPLAYER] missing '{key}'")

        return errors, warnings

    def open_workshop_page(self):
        item_id = self.item_id_var.get()
        if item_id and item_id != "0":
            webbrowser.open(f"https://steamcommunity.com/sharedfiles/filedetails/?id={item_id}")
        else:
            messagebox.showinfo("Info", "No valid Workshop ID available.")

    def update_item_id_from_vdf(self, vdf_path):
        def _update():
            try:
                if os.path.exists(vdf_path):
                    with open(vdf_path, 'r') as f:
                        content = f.read()
                    match = re.search(r'"publishedfileid"\s+"(\d+)"', content)
                    if match:
                        new_id = match.group(1)
                        if new_id != "0":
                            self.item_id_var.set(new_id)
                            self.log(f"Detected new Workshop ID: {new_id}")
            except Exception as e:
                self.log(f"Failed to parse VDF for ID: {e}")
        self.root.after(0, _update)

    def start_upload(self):
        # Validation
        title = self.title_var.get()
        if len(title) > STEAM_TITLE_LIMIT:
            messagebox.showerror("Title Too Long", f"Your title is {len(title)} characters long. The maximum is {STEAM_TITLE_LIMIT}.")
            return
        if not title:
            messagebox.showerror("Missing Title", "The workshop item must have a title.")
            return

        desc = self.desc_text.get("1.0", "end-1c")
        if len(desc) > STEAM_DESC_LIMIT:
            messagebox.showerror("Description Too Long", f"Your description is {len(desc)} characters long. The maximum is {STEAM_DESC_LIMIT}.")
            return

        sc = self.steamcmd_path.get()
        content = self.mod_path.get()
        preview = self.preview_path.get()
        user = self.username_var.get().strip()
        pwd = self.password_var.get()
        use_cached = self.use_cached_creds_var.get()
        
        if not all([sc, content, preview]):
            messagebox.showerror("Error", "Missing required fields (SteamCMD, Content Folder, Preview Image).")
            return

        if not use_cached and not user:
            messagebox.showerror("Error", "Steam Username is required unless 'USE CACHED CREDENTIALS' is enabled.")
            return
            
        if not os.path.exists(sc):
            messagebox.showerror("Error", "SteamCMD executable not found.")
            return

        # Safety Check
        issues = self.scan_mod_safety(content)
        issues.extend(self.scan_asset_references(content))
        if issues:
            if not self.show_safety_warning(issues): return

        # Content Validity Check
        val_errors, val_warnings = self.validate_content_structure(content)
        if val_errors:
            messagebox.showerror("Validation Error", "Content Validation Failed:\n\n" + "\n".join(val_errors))
            return
        if val_warnings:
            if not messagebox.askyesno("Validation Warnings", "Content Validation Warnings:\n\n" + "\n".join(val_warnings) + "\n\nContinue upload anyway?"):
                return

        # TRN Checks
        le_issues, dup_issues = self.scan_trn_safety(content)
        
        if dup_issues:
             if messagebox.askyesno("TRN Format Warning", 
                                   f"Found {len(dup_issues)} .trn files with duplicate [Size] headers.\n"
                                   "This causes map loading errors.\n"
                                   "Would you like to automatically remove the duplicates (keeping the top one)?", icon='warning'):
                fixed_count = self.fix_trn_duplicates(dup_issues)
                messagebox.showinfo("Fixed", f"Fixed duplicate headers in {fixed_count} files.")
             elif not messagebox.askyesno("Confirm Upload", "Uploading with duplicate TRN headers will likely break the map.\nContinue anyway?"):
                return

        if le_issues:
            if messagebox.askyesno("TRN Format Warning", 
                                   f"Found {len(le_issues)} .trn files with incorrect line endings.\n"
                                   "The game requires CRLF (Windows) line endings.\n"
                                   "Would you like to automatically fix them?", icon='warning'):
                fixed_count = self.fix_trn_files(le_issues)
                messagebox.showinfo("Fixed", f"Corrected line endings in {fixed_count} files.")
            elif not messagebox.askyesno("Confirm Upload", "Uploading with incorrect TRN line endings may cause bugs.\nContinue anyway?"):
                return

        # Legacy MAP Check
        legacy_maps = self.scan_legacy_files(content)
        if legacy_maps:
            if messagebox.askyesno("Legacy Content Warning", 
                                   f"Found {len(legacy_maps)} .map files.\n"
                                   "These are legacy Battlezone 1.5 texture files and are NOT used by Redux.\n"
                                   "They will increase download size unnecessarily.\n\n"
                                   "Would you like to automatically delete them?", icon='warning'):
                deleted_count = self.delete_legacy_files(legacy_maps)
                messagebox.showinfo("Cleanup Complete", f"Deleted {deleted_count} legacy files.")
            elif not messagebox.askyesno("Confirm Upload", "Continue upload with legacy files included?"):
                return

        if not self._confirm_upload_plan(content, preview, use_cached):
            return

        self.save_config()
        
        # Create VDF
        try:
            vdf_path = os.path.join(self.base_dir, "upload.vdf")
            appid = self.games[self.game_var.get()]["appid"]
            desc = self.desc_text.get("1.0", "end-1c")
            vis = self.visibility_var.get().split()[0]

            vdf_content = self._build_upload_vdf_content(
                appid=appid,
                publishedfileid=self.item_id_var.get(),
                contentfolder=content,
                previewfile=preview,
                visibility=vis,
                title=self.title_var.get(),
                description=desc,
                changenote=self.note_var.get(),
            )
            with open(vdf_path, "w", encoding="utf-8") as f:
                f.write(vdf_content)
            self.log(f"Generated VDF at {vdf_path}")
            
        except Exception as e:
            self.log(f"Error creating VDF: {e}")
            return

        vdf_path = os.path.join(self.base_dir, "upload.vdf")
        # Run SteamCMD
        # We use a separate thread to not freeze UI, but we might need a new console for 2FA
        self._set_busy("Upload", True)
        threading.Thread(target=self.run_steamcmd, args=(sc, user, pwd, vdf_path)).start()

    def run_steamcmd(self, exe, user, pwd, vdf):
        self.log("Starting SteamCMD...")
        
        use_cached = self.use_cached_creds_var.get()
        cmd = [exe, "+login"]
        if user:
            cmd.append(user)
        
        if not use_cached:
            if not user:
                self.log("Execution Error: Username is required when cached credentials are disabled.")
                self._set_busy("Upload", False)
                return
            if pwd:
                cmd.append(pwd)
            guard_code = self.steam_guard_var.get()
            if guard_code:
                cmd.append(guard_code)
        else:
            if user:
                self.log(f"Attempting login using cached credentials for '{user}'...")
            else:
                self.log("Attempting login using cached credentials (no username provided)...")
            
        cmd.extend(["+workshop_build_item", vdf, "+quit"])
        
        try:
            # On Windows, CREATE_NEW_CONSOLE allows user to interact (enter 2FA) if needed
            creation_flags = subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS else 0
            
            self.steamcmd_process = subprocess.Popen(cmd, creationflags=creation_flags)
            self.steamcmd_process.wait()
            p = self.steamcmd_process
            self.steamcmd_process = None
            
            if p.returncode == 0:
                self.log("SteamCMD finished successfully.")
                self.update_item_id_from_vdf(vdf)
                
                # Apply Tags if present
                if self.tags_var.get().strip():
                    self.update_workshop_tags()
                
                self.root.after(0, lambda: messagebox.showinfo("Success", "SteamCMD process finished.\nCheck the console window for upload status."))
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

        if switch_to_upload:
            self.notebook.select(self.upload_tab)

        if not quiet:
            self.log(f"Upload target set to Workshop ID {item_id}: {title}")
        return True

    def _resolve_vanity_to_steamid(self, vanity, api_key):
        url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
        r = self._request_with_retry(
            "GET",
            url,
            operation_name="Resolve vanity URL",
            params={"key": api_key, "vanityurl": vanity},
            timeout=10
        )
        data = r.json().get("response", {})
        if data.get("success") == 1:
            return data.get("steamid")
        return None

    def resolve_steam_id(self, identity_input, api_key):
        text = (identity_input or "").strip()
        if not text:
            return None

        # Direct SteamID64 input
        if text.isdigit() and len(text) == 17:
            return text

        # https://steamcommunity.com/profiles/<steamid64>
        profiles_match = re.search(r"steamcommunity\.com/profiles/(\d{17})", text, re.IGNORECASE)
        if profiles_match:
            return profiles_match.group(1)

        vanity = text
        # https://steamcommunity.com/id/<vanity>
        vanity_match = re.search(r"steamcommunity\.com/id/([^/?#]+)", text, re.IGNORECASE)
        if vanity_match:
            vanity = vanity_match.group(1)
        else:
            vanity = re.sub(r"^https?://", "", vanity, flags=re.IGNORECASE).strip().strip("/")
            if vanity.lower().startswith("id/"):
                vanity = vanity[3:].strip("/")

        if vanity:
            try:
                return self._resolve_vanity_to_steamid(vanity, api_key)
            except Exception:
                return None
        return None

    def _extract_loginusers_accounts(self, vdf_path):
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        parsed = self._parse_vdf_text(content)
        users = self._dict_get_ci(parsed, "users", {})
        if not isinstance(users, dict):
            return []

        accounts = []
        for steam_id, info in users.items():
            if not (str(steam_id).isdigit() and len(str(steam_id)) == 17):
                continue
            accounts.append({
                "steamid": str(steam_id),
                "account_name": str(self._dict_get_ci(info, "AccountName", "")).strip(),
                "persona_name": str(self._dict_get_ci(info, "PersonaName", "")).strip(),
                "most_recent": str(self._dict_get_ci(info, "MostRecent", "")).strip()
            })
        return accounts

    def detect_local_steam_identity(self):
        candidates = []

        steamcmd_exe = self.steamcmd_path.get().strip()
        if steamcmd_exe:
            candidates.append(os.path.join(os.path.dirname(steamcmd_exe), "config", "loginusers.vdf"))

        for env_var in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            base = os.environ.get(env_var, "")
            if base:
                candidates.append(os.path.join(base, "Steam", "config", "loginusers.vdf"))

        candidates.append(os.path.join(self.base_dir, "steamcmd", "config", "loginusers.vdf"))

        seen = set()
        for path in candidates:
            norm = os.path.normpath(path)
            if norm in seen or not os.path.exists(norm):
                continue
            seen.add(norm)
            try:
                accounts = self._extract_loginusers_accounts(norm)
                if not accounts:
                    continue
                accounts.sort(key=lambda a: (a.get("most_recent") != "1", a.get("account_name", "")))
                account = accounts[0]
                account["source"] = norm
                return account
            except Exception:
                continue
        return None

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
        self._set_busy("Refresh", True)
        threading.Thread(target=self._refresh_worker, args=(identity_input,), daemon=True).start()

    def _refresh_worker(self, identity_input):
        try:
            # 1. Get SteamID
            api_key = self.api_key_var.get()
            steam_id = self.resolve_steam_id(identity_input, api_key)

            if not steam_id:
                self.root.after(0, lambda: self.log("Error: Could not resolve owner. Use SteamID64, profile URL, vanity URL, or 'USE CURRENT STEAM LOGIN'."))
                return

            self.root.after(0, lambda: self.manage_identity_var.set(steam_id))

            # 2. Query items
            appid = self.games[self.game_var.get()]["appid"]
            query_url = f"https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
            params = {
                "key": api_key, "creator_appid": appid, "appid": appid,
                "numperpage": 100, "return_metadata": 1, "steamid": steam_id
            }
            r = self._request_with_retry("GET", query_url, operation_name="Query Workshop files", params=params, timeout=10)
            items = r.json().get("response", {}).get("publishedfiledetails", [])
            
            self.root.after(0, lambda: self.tree.delete(*self.tree.get_children()))
            
            vis_map = {0: "Public", 1: "Friends", 2: "Private"}
            for item in items:
                ts = datetime.fromtimestamp(item['time_updated']).strftime('%Y-%m-%d %H:%M')
                vis = vis_map.get(item['visibility'], "Unknown")
                self.root.after(0, lambda i=item, v=vis, t=ts: self.tree.insert("", "end", values=(i['title'], i['publishedfileid'], v, t)))

        except Exception as e:
            self.root.after(0, lambda: self.log(f"API Error: {self._friendly_api_error(e)}"))
        finally:
            self._set_busy("Refresh", False)

    def update_workshop_tags(self):
        """Uses the Steam Web API to set tags on the workshop item."""
        api_key = self.api_key_var.get()
        item_id = self.item_id_var.get()
        tags_str = self.tags_var.get()
        
        if not api_key or not item_id or item_id == "0" or not tags_str:
            return
            
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]
        if not tags: return
        
        self.log(f"Updating Workshop tags: {', '.join(tags)}...")
        
        def _worker():
            try:
                # IPublishedFileService/Update/v1
                url = "https://api.steampowered.com/IPublishedFileService/Update/v1/"
                # The API usually expects tags to be passed as tags[0], tags[1]...
                data = {
                    "key": api_key,
                    "publishedfileid": item_id,
                    "appid": self.games[self.game_var.get()]["appid"],
                }
                for i, tag in enumerate(tags):
                    data[f"tags[{i}]"] = tag
                
                self._request_with_retry("POST", url, operation_name="Update Workshop tags", data=data, timeout=10)
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
            url = "https://api.steampowered.com/IPublishedFileService/GetPublishedFileDetails/v1/"
            r = self._request_with_retry(
                "POST",
                url,
                operation_name="Fetch Workshop item details",
                data={"key": api_key, "itemcount": 1, "publishedfileids[0]": item_id},
                timeout=10
            )
            
            details = r.json().get("response", {}).get("publishedfiledetails", [{}])[0]
            if not details:
                self.root.after(0, lambda: self.log(f"Could not fetch details for {item_id}"))
                return

            # Download preview image
            preview_url = details.get("preview_url")
            preview_local_path = ""
            if preview_url:
                img_res = self._request_with_retry("GET", preview_url, operation_name="Download Workshop preview", stream=True, timeout=10)
                if img_res.ok:
                    preview_local_path = os.path.join(self.temp_dir, f"{item_id}.jpg")
                    with open(preview_local_path, 'wb') as f: f.write(img_res.content)
            
            # Map visibility int to combobox string
            vis_map = {0: "0 (Public)", 1: "1 (Friends)", 2: "2 (Private)"}
            vis_str = vis_map.get(details.get("visibility"), "0 (Public)")

            def do_populate():
                self.item_id_var.set(details.get("publishedfileid", "0"))
                self.title_var.set(details.get("title", ""))
                self.desc_text.delete("1.0", "end")
                self.desc_text.insert("1.0", details.get("description", ""))
                self.preview_path.set(preview_local_path)
                self.visibility_var.set(vis_str)
                self.notebook.select(self.upload_tab)
            
            self.root.after(0, do_populate)
        except Exception as e:
            self.root.after(0, lambda: self.log(f"API Error: {self._friendly_api_error(e)}"))
        finally:
            self._set_busy("Prepare Update", False)

    def analyze_last_upload_log(self):
        sc_exe = self.steamcmd_path.get()
        if not sc_exe: return None
        
        base_dir = os.path.dirname(sc_exe)
        appid = self.games[self.game_var.get()]["appid"]
        log_path = os.path.join(base_dir, "workshopbuilds", f"depot_build_{appid}.log")
        
        if not os.path.exists(log_path):
            return None
            
        try:
            with open(log_path, 'r', errors='ignore') as f:
                lines = f.readlines()
                
            errors = [l.strip() for l in lines if "error" in l.lower() or "failed" in l.lower()]
            if errors:
                return "\n".join(errors[-5:]) # Last 5 errors
        except Exception: pass
        return None

    def show_steam_logs(self):
        sc_exe = self.steamcmd_path.get()
        if not sc_exe:
            messagebox.showerror("Error", "SteamCMD path not set.")
            return
            
        base_dir = os.path.dirname(sc_exe)
        appid = self.games[self.game_var.get()]["appid"]
        
        logs = [
            ("Build Log", os.path.join(base_dir, "workshopbuilds", f"depot_build_{appid}.log")),
            ("Transfer Log", os.path.join(base_dir, "logs", "Workshop_log.txt"))
        ]
        
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
