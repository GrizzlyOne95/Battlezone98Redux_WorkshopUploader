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

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Platform check
IS_WINDOWS = sys.platform == "win32"

# --- CONFIGURATION ---
CONFIG_FILE = "uploader_config.json"
STEAM_TITLE_LIMIT = 128
STEAM_DESC_LIMIT = 8000

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
            
        self.temp_dir = os.path.join(self.base_dir, "temp_previews")
        os.makedirs(self.temp_dir, exist_ok=True)

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
        self.api_key_var = tk.StringVar(value=self.config.get("api_key", ""))
        
        last_game = self.config.get("last_game", "BZ98R")
        if last_game not in self.games: last_game = "BZ98R"
        self.game_var = tk.StringVar(value=last_game)
        
        self.mod_path = tk.StringVar()
        self.preview_path = tk.StringVar()
        self.title_var = tk.StringVar()
        self.title_var.trace_add("write", self._update_title_counter)
        self.desc_var = tk.StringVar()
        self.note_var = tk.StringVar(value="Initial Release")
        self.visibility_var = tk.StringVar(value="0") # 0=Public, 1=Friends, 2=Private
        self.item_id_var = tk.StringVar(value="0")
        
        self.username_var = tk.StringVar(value=self.config.get("username", ""))
        self.password_var = tk.StringVar()
        self.steam_guard_var = tk.StringVar()
        
        self.setup_styles()
        self.setup_ui()
        
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
                except: pass

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return json.load(f)
            except: pass
        return {}

    def save_config(self):
        cfg = {
            "steamcmd_path": self.steamcmd_path.get(),
            "api_key": self.api_key_var.get(),
            "last_game": self.game_var.get(),
            "username": self.username_var.get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f: json.dump(cfg, f, indent=4)
        except: pass

    def on_close(self):
        self.save_config()
        # Clean up temp preview files
        try:
            for f in os.listdir(self.temp_dir): os.remove(os.path.join(self.temp_dir, f))
            os.rmdir(self.temp_dir)
        except: pass
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
        
        # Credentials
        ttk.Label(cfg_frame, text="Steam Username:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(cfg_frame, textvariable=self.username_var).grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        
        ttk.Label(cfg_frame, text="Password:").grid(row=1, column=2, sticky="e", pady=5)
        ttk.Entry(cfg_frame, textvariable=self.password_var, show="*").grid(row=1, column=3, sticky="ew", padx=5)
        
        ttk.Label(cfg_frame, text="2FA Code:").grid(row=1, column=4, sticky="e", pady=5)
        ttk.Entry(cfg_frame, textvariable=self.steam_guard_var, width=10).grid(row=1, column=5, sticky="w", padx=5)
        
        # API Key
        ttk.Label(cfg_frame, text="Steam Web API Key:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(cfg_frame, textvariable=self.api_key_var, show="*").grid(row=2, column=1, sticky="ew", padx=5)
        api_help = ttk.Button(cfg_frame, text="?", command=self.open_api_key_link, width=3)
        api_help.grid(row=2, column=2, padx=5)
        ToolTip(api_help, "Needed for the 'Manage' tab.\nGet one from steamcommunity.com/dev/apikey")
        
        cfg_frame.columnconfigure(1, weight=1)
        cfg_frame.columnconfigure(3, weight=1)

        # --- MOD DETAILS ---
        mod_frame = ttk.LabelFrame(parent_tab, text=" MOD DETAILS ", padding=10)
        mod_frame.pack(fill="both", expand=True, pady=10)
        
        # Content Path
        ttk.Label(mod_frame, text="Content Folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(mod_frame, textvariable=self.mod_path).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(mod_frame, text="BROWSE", command=self.browse_content).grid(row=0, column=2)
        
        # Preview Image
        ttk.Label(mod_frame, text="Preview Image:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(mod_frame, textvariable=self.preview_path).grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(mod_frame, text="BROWSE", command=self.browse_preview).grid(row=1, column=2, pady=5)
        
        # Title
        ttk.Label(mod_frame, text="Title:").grid(row=2, column=0, sticky="w")
        ttk.Entry(mod_frame, textvariable=self.title_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=5)
        
        self.title_char_label = ttk.Label(mod_frame, text=f"0 / {STEAM_TITLE_LIMIT}")
        self.title_char_label.grid(row=2, column=3, sticky="w", padx=5)
        
        # Description
        ttk.Label(mod_frame, text="Description:").grid(row=3, column=0, sticky="nw", pady=5)
        self.desc_text = tk.Text(mod_frame, height=5, bg="#1a1a1a", fg=self.colors["accent"], insertbackground=self.colors["highlight"], font=("Consolas", 10))
        self.desc_text.grid(row=3, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        self.desc_text.bind("<KeyRelease>", self._update_desc_counter)
        
        self.desc_char_label = ttk.Label(mod_frame, text=f"0 / {STEAM_DESC_LIMIT}")
        self.desc_char_label.grid(row=3, column=3, sticky="nw", pady=5, padx=5)
        
        # Metadata Row
        meta_row = ttk.Frame(mod_frame)
        meta_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=5)
        
        ttk.Label(meta_row, text="Visibility:").pack(side="left")
        ttk.Combobox(meta_row, textvariable=self.visibility_var, values=["0 (Public)", "1 (Friends)", "2 (Private)"], state="readonly", width=15).pack(side="left", padx=5)
        
        ttk.Label(meta_row, text="Workshop ID (0=New):").pack(side="left", padx=(20, 5))
        ttk.Entry(meta_row, textvariable=self.item_id_var, width=15).pack(side="left", padx=5)
        
        link_btn = ttk.Button(meta_row, text="↗", width=3, command=self.open_workshop_page)
        link_btn.pack(side="left", padx=2)
        ToolTip(link_btn, "Open Workshop Page")
        
        ttk.Label(meta_row, text="Change Note:").pack(side="left", padx=(20, 5))
        ttk.Entry(meta_row, textvariable=self.note_var).pack(side="left", fill="x", expand=True, padx=5)
        
        mod_frame.columnconfigure(1, weight=1)

        # --- ACTIONS ---
        btn_frame = ttk.Frame(parent_tab)
        btn_frame.pack(fill="x", pady=10)
        
        self.log_box = tk.Text(parent_tab, height=8, state="disabled", bg="#050505", fg=self.colors["fg"], font=("Consolas", 9))
        self.log_box.pack(fill="x", pady=(0, 10))
        
        ttk.Button(btn_frame, text="UPLOAD TO STEAM WORKSHOP", command=self.start_upload, style="Success.TButton").pack(side="left", fill="x", expand=True, ipady=5)
        ttk.Button(btn_frame, text="LOGS", width=10, command=self.show_steam_logs).pack(side="right", fill="y", padx=(5,0))

    def setup_manage_tab(self, parent_tab):
        # --- CONTROLS ---
        ctrl_frame = ttk.Frame(parent_tab, padding=10)
        ctrl_frame.pack(fill="x")

        ttk.Button(ctrl_frame, text="Refresh List", command=self.refresh_workshop_items).pack(side="left")
        
        update_btn = ttk.Button(ctrl_frame, text="Prepare for Update", command=self.prepare_update)
        update_btn.pack(side="left", padx=10)
        ToolTip(update_btn, "Populates the Upload tab with the selected item's data.\nYou will then need to select the content folder and click Upload.")
        
        info_label = ttk.Label(ctrl_frame, text="Requires API Key and a valid Username (Vanity URL or SteamID64) in Config.", foreground="#ffff44")
        info_label.pack(side="right")

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
                except: pass
                return

            try:
                if os.path.getsize(f) > 1024 * 1024:
                    if messagebox.askyesno("Image Too Large", f"Preview image is > 1MB. Auto-resize and compress it?"):
                        new_path = self.resize_preview_image(f)
                        if new_path: self.preview_path.set(new_path)
            except Exception as e: self.log(f"Image size check failed: {e}")

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
            except: rel_path = path
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

        win.result = False
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", pady=10, padx=10)
        ttk.Button(btn_frame, text="OPEN SELECTED FILE", command=on_open).pack(side="left")
        ttk.Button(btn_frame, text="CANCEL UPLOAD", command=win.destroy).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="IGNORE & CONTINUE", command=on_continue, style="Success.TButton").pack(side="right")
        
        win.transient(self.root)
        win.grab_set()
        self.root.wait_window(win)
        return getattr(win, 'result', False)

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
        user = self.username_var.get()
        pwd = self.password_var.get()
        
        if not all([sc, content, preview, user]):
            messagebox.showerror("Error", "Missing required fields (SteamCMD, Content, Preview, Username).")
            return
            
        if not os.path.exists(sc):
            messagebox.showerror("Error", "SteamCMD executable not found.")
            return

        # Safety Check
        issues = self.scan_mod_safety(content)
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

        self.save_config()
        
        # Create VDF
        try:
            vdf_path = os.path.join(self.base_dir, "upload.vdf")
            appid = self.games[self.game_var.get()]["appid"]
            desc = self.desc_text.get("1.0", "end-1c")
            vis = self.visibility_var.get().split()[0]
            
            vdf_content = f"""
"workshopitem"
{{
    "appid" "{appid}"
    "publishedfileid" "{self.item_id_var.get()}"
    "contentfolder" "{os.path.abspath(content)}"
    "previewfile" "{os.path.abspath(preview)}"
    "visibility" "{vis}"
    "title" "{self.title_var.get()}"
    "description" "{desc}"
    "changenote" "{self.note_var.get()}"
}}
"""
            with open(vdf_path, "w") as f:
                f.write(vdf_content)
            self.log(f"Generated VDF at {vdf_path}")
            
        except Exception as e:
            self.log(f"Error creating VDF: {e}")
            return

        # Run SteamCMD
        # We use a separate thread to not freeze UI, but we might need a new console for 2FA
        threading.Thread(target=self.run_steamcmd, args=(sc, user, pwd, vdf_path)).start()

    def run_steamcmd(self, exe, user, pwd, vdf):
        self.log("Starting SteamCMD...")
        
        cmd = [exe, "+login", user]
        if pwd:
            cmd.append(pwd)
        guard_code = self.steam_guard_var.get()
        if guard_code:
            cmd.append(guard_code)
            
        cmd.extend(["+workshop_build_item", vdf, "+quit"])
        
        try:
            # On Windows, CREATE_NEW_CONSOLE allows user to interact (enter 2FA) if needed
            creation_flags = subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS else 0
            
            p = subprocess.Popen(cmd, creationflags=creation_flags)
            p.wait()
            
            if p.returncode == 0:
                self.log("SteamCMD finished successfully.")
                self.update_item_id_from_vdf(vdf)
                self.root.after(0, lambda: messagebox.showinfo("Success", "SteamCMD process finished.\nCheck the console window for upload status."))
            else:
                self.log(f"SteamCMD exited with code {p.returncode}")
                
                analysis = self.analyze_last_upload_log()
                msg = f"SteamCMD encountered an error (Code {p.returncode})."
                if analysis:
                    msg += f"\n\nPossible Errors found in log:\n{analysis}"
                
                def show_err():
                    if messagebox.askyesno("Upload Error", f"{msg}\n\nOpen logs to investigate?"):
                        self.show_steam_logs()
                self.root.after(0, show_err)
                
        except Exception as e:
            self.log(f"Execution Error: {e}")

    def refresh_workshop_items(self):
        if not self.api_key_var.get() or not self.username_var.get():
            messagebox.showerror("Error", "API Key and Username are required for this feature.")
            return
        self.log("Fetching workshop items...")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            # 1. Get SteamID
            api_key = self.api_key_var.get()
            user_input = self.username_var.get()
            
            steam_id = None
            if user_input.isdigit() and len(user_input) == 17:
                steam_id = user_input
            else: # Assume vanity URL
                vanity_url = f"http://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key={api_key}&vanityurl={user_input}"
                r = requests.get(vanity_url)
                r.raise_for_status()
                data = r.json().get("response", {})
                if data.get("success") == 1:
                    steam_id = data.get("steamid")

            if not steam_id:
                self.root.after(0, lambda: self.log("Error: Could not resolve username to SteamID."))
                return

            # 2. Query items
            appid = self.games[self.game_var.get()]["appid"]
            query_url = f"https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
            params = {
                "key": api_key, "creator_appid": appid, "appid": appid,
                "numperpage": 100, "return_metadata": 1, "steamid": steam_id
            }
            r = requests.get(query_url, params=params)
            r.raise_for_status()
            items = r.json().get("response", {}).get("publishedfiledetails", [])
            
            self.root.after(0, lambda: self.tree.delete(*self.tree.get_children()))
            
            vis_map = {0: "Public", 1: "Friends", 2: "Private"}
            for item in items:
                from datetime import datetime
                ts = datetime.fromtimestamp(item['time_updated']).strftime('%Y-%m-%d %H:%M')
                vis = vis_map.get(item['visibility'], "Unknown")
                self.root.after(0, lambda i=item, v=vis, t=ts: self.tree.insert("", "end", values=(i['title'], i['publishedfileid'], v, t)))

        except Exception as e:
            self.root.after(0, lambda: self.log(f"API Error: {e}"))

    def prepare_update(self):
        selected = self.tree.selection()
        if not selected: return
        
        item_id = self.tree.item(selected[0])['values'][1]
        self.log(f"Fetching details for item {item_id}...")
        threading.Thread(target=self._prepare_update_worker, args=(item_id,), daemon=True).start()

    def _prepare_update_worker(self, item_id):
        try:
            api_key = self.api_key_var.get()
            url = "https://api.steampowered.com/IPublishedFileService/GetPublishedFileDetails/v1/"
            r = requests.post(url, data={"key": api_key, "itemcount": 1, "publishedfileids[0]": item_id})
            r.raise_for_status()
            
            details = r.json().get("response", {}).get("publishedfiledetails", [{}])[0]
            if not details:
                self.root.after(0, lambda: self.log(f"Could not fetch details for {item_id}"))
                return

            # Download preview image
            preview_url = details.get("preview_url")
            preview_local_path = ""
            if preview_url:
                img_res = requests.get(preview_url, stream=True)
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
            self.root.after(0, lambda: self.log(f"API Error: {e}"))

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
        except: pass
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