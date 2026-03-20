import sys
import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import shutil
import io
import zipfile

# Mock out GUI and network libraries that might fail in a headless test environment
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.ttk'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['ctypes'] = MagicMock()
sys.modules['keyring'] = MagicMock()

# Add parent directory to path to import uploader
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import uploader
from app_file_manager import AppFileManager
from content_fixes import ContentFixer
from memory_analyzer import MemoryAnalyzer
from upload_preflight import UploadPreflight

class DummyVar:
    def __init__(self, value=""):
        self._value = value
    def get(self):
        return self._value
    def set(self, value):
        self._value = value

class TestWorkshopUploader(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for file operations
        self.test_dir = tempfile.mkdtemp()

        # Instantiate the uploader with a mocked root
        mock_root = MagicMock()
        self.uploader = uploader.WorkshopUploader(mock_root)

        # Redirect log to not pollute stdout during tests
        self.uploader.log = MagicMock()
        uploader.messagebox.showerror.reset_mock()
        uploader.messagebox.askyesno.return_value = True

    def tearDown(self):
        # Clean up the temporary directory
        shutil.rmtree(self.test_dir)

    def test_legacy_files(self):
        """Test scan_legacy_files and delete_legacy_files detect and remove .map files."""
        # Create dummy legacy files
        map_file1 = os.path.join(self.test_dir, "test1.map")
        map_file2 = os.path.join(self.test_dir, "test2.map")
        with open(map_file1, "w") as f: f.write("dummy map content")
        with open(map_file2, "w") as f: f.write("dummy map content")

        # Also create a non-legacy file
        good_file = os.path.join(self.test_dir, "test1.trn")
        with open(good_file, "w") as f: f.write("good file content")

        # Scan for legacy files
        legacy_files = self.uploader.scan_legacy_files(self.test_dir)
        self.assertEqual(len(legacy_files), 2)
        self.assertIn(map_file1, legacy_files)
        self.assertIn(map_file2, legacy_files)

        # Delete legacy files
        deleted_count = self.uploader.delete_legacy_files(legacy_files)
        self.assertEqual(deleted_count, 2)

        # Verify files are deleted
        self.assertFalse(os.path.exists(map_file1))
        self.assertFalse(os.path.exists(map_file2))
        self.assertTrue(os.path.exists(good_file))

    def test_trn_safety(self):
        """Test scan_trn_safety detects bad line endings and duplicate [Size] headers."""
        bad_le_file = os.path.join(self.test_dir, "bad_le.trn")
        with open(bad_le_file, "wb") as f:
            f.write(b"[Size]\nTileSize=8\n") # missing CR

        dup_size_file = os.path.join(self.test_dir, "dup_size.trn")
        with open(dup_size_file, "wb") as f: # Use wb to explicitly control line endings
            f.write(b"[Size]\r\nTileSize=8\r\n[Size]\r\nTileSize=16\r\n")

        good_trn_file = os.path.join(self.test_dir, "good.trn")
        with open(good_trn_file, "wb") as f:
            f.write(b"[Size]\r\nTileSize=8\r\n")

        le_issues, dup_issues = self.uploader.scan_trn_safety(self.test_dir)

        self.assertEqual(len(le_issues), 1)
        self.assertEqual(le_issues[0], bad_le_file)

        self.assertEqual(len(dup_issues), 1)
        self.assertEqual(dup_issues[0], dup_size_file)

    def test_fix_trn_files(self):
        """Test fix_trn_files corrects line endings."""
        bad_le_file = os.path.join(self.test_dir, "bad_le.trn")
        with open(bad_le_file, "wb") as f:
            f.write(b"[Size]\nTileSize=8\n")

        fixed_count = self.uploader.fix_trn_files([bad_le_file])
        self.assertEqual(fixed_count, 1)

        with open(bad_le_file, "rb") as f:
            content = f.read()
            self.assertEqual(content, b"[Size]\r\nTileSize=8\r\n")

    def test_fix_trn_duplicates(self):
        """Test fix_trn_duplicates removes duplicate headers."""
        dup_size_file = os.path.join(self.test_dir, "dup_size.trn")
        with open(dup_size_file, "w", encoding="utf-8") as f:
            f.write("[Size]\nTileSize=8\n[Size]\nTileSize=16\n[Other]\nTest=1\n")

        fixed_count = self.uploader.fix_trn_duplicates([dup_size_file])
        self.assertEqual(fixed_count, 1)

        with open(dup_size_file, "r", encoding="utf-8") as f:
            content = f.read()
            # Should keep the first [Size] and remove the second one
            # Including its content until the next header
            self.assertEqual(content, "[Size]\nTileSize=8\n[Other]\nTest=1\n")

    def test_validate_content_structure_missing_ini(self):
        """Test validate_content_structure identifies missing INI files."""
        errors, warnings = self.uploader.validate_content_structure(self.test_dir)
        self.assertTrue(any("Missing configuration (.ini) file" in err for err in errors))

    def test_validate_content_structure_desktop_ini(self):
        """Test validate_content_structure removes desktop.ini before checking."""
        desktop_ini_path = os.path.join(self.test_dir, "desktop.ini")
        with open(desktop_ini_path, "w") as f: f.write("dummy")

        # Still missing the real INI
        errors, warnings = self.uploader.validate_content_structure(self.test_dir)
        self.assertTrue(any("Missing configuration (.ini) file" in err for err in errors))
        self.assertFalse(os.path.exists(desktop_ini_path)) # Verify it was deleted

    def test_validate_content_structure_multiplayer(self):
        """Test validate_content_structure with valid multiplayer structure."""
        ini_content = "[DESCRIPTION]\nmissionName=\"test\"\n[WORKSHOP]\nmapType=\"multiplayer\"\n[MULTIPLAYER]\nminPlayers=2\nmaxPlayers=4\ngameType=S\n"
        with open(os.path.join(self.test_dir, "test.ini"), "w") as f: f.write(ini_content)

        # Create required files
        for ext in [".hg2", ".trn", ".mat", ".bzn", ".lgt", ".bmp", ".des", ".vxt"]:
            with open(os.path.join(self.test_dir, f"test{ext}"), "w") as f: f.write("")

        errors, warnings = self.uploader.validate_content_structure(self.test_dir)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 0)

    def test_scan_asset_references(self):
        """Test scan_asset_references finds missing ODF/material assets."""
        # Create an ODF file with a missing geometry reference
        odf_file = os.path.join(self.test_dir, "test.odf")
        with open(odf_file, "w") as f:
            f.write('geometryName = "missing_model.xsi"\n')

        # Create a material file with a missing texture reference
        mat_file = os.path.join(self.test_dir, "test.material")
        with open(mat_file, "w") as f:
            f.write('texture missing_tex.tga\n')

        issues = self.uploader.scan_asset_references(self.test_dir)

        self.assertEqual(len(issues), 2)

        # Issues are tuples: (path, issue_type, detail, line)
        odf_issue = next(i for i in issues if i[0] == odf_file)
        self.assertEqual(odf_issue[1], "Missing Asset")
        self.assertTrue("missing_model.xsi" in odf_issue[2])

        mat_issue = next(i for i in issues if i[0] == mat_file)
        self.assertEqual(mat_issue[1], "Missing Asset")
        self.assertTrue("missing_tex.tga" in mat_issue[2])

    def test_memory_analyzer_detects_orphans_and_textures(self):
        analyzer = MemoryAnalyzer()

        with open(os.path.join(self.test_dir, "map.ini"), "w", encoding="utf-8") as f:
            f.write("[WORKSHOP]\nmapType=\"mod\"\n")
        with open(os.path.join(self.test_dir, "script.odf"), "w", encoding="utf-8") as f:
            f.write('geometryName = "used_model.xsi"\n')
        with open(os.path.join(self.test_dir, "used_model.xsi"), "w", encoding="utf-8") as f:
            f.write("mesh")
        with open(os.path.join(self.test_dir, "orphan.png"), "wb") as f:
            f.write(b"pngdata")

        analysis = analyzer.analyze(self.test_dir)

        self.assertEqual(analysis["counts"]["Texture"], 1)
        self.assertIn("orphan.png", analysis["non_dds_textures"])
        self.assertIn("orphan.png", analysis["orphans"])
        self.assertNotIn("used_model.xsi", analysis["orphans"])

    def test_memory_analyzer_report_mentions_orphans(self):
        analyzer = MemoryAnalyzer()
        report = analyzer.build_report({
            "disk_mb": 1.25,
            "vram_mb": 12.5,
            "counts": {"Texture": 1, "Model": 2, "Audio": 0, "Script": 3, "Other": 4},
            "non_dds_textures": ["orphan.png"],
            "orphans": ["orphan.png", "unused.wav"],
        })
        self.assertIn("MEMORY ANALYSIS REPORT", report)
        self.assertIn("non-DDS textures", report)
        self.assertIn("ORPHANS", report)
        self.assertIn("orphan.png", report)

    def test_build_upload_vdf_content_escapes_special_chars(self):
        content = self.uploader._build_upload_vdf_content(
            appid="301650",
            publishedfileid="123",
            contentfolder=r"C:\mods\test",
            previewfile=r"C:\mods\preview \"new\".jpg",
            visibility="0",
            title='A "Quoted" Title',
            description="Line1\nLine2",
            changenote="Backslash \\ test"
        )
        self.assertIn('\\"Quoted\\"', content)
        self.assertIn("Line1\\nLine2", content)
        self.assertIn("\\\\", content)

    def test_workshop_backend_builds_manual_steamcmd_command(self):
        cmd = self.uploader.workshop_backend.build_steamcmd_command(
            exe="steamcmd.exe",
            user="tester",
            pwd="secret",
            vdf="upload.vdf",
            use_cached=False,
            guard_code="abc123",
        )
        self.assertEqual(cmd, [
            "steamcmd.exe", "+login", "tester", "secret", "abc123",
            "+workshop_build_item", "upload.vdf", "+quit"
        ])

    def test_workshop_backend_requires_username_without_cached_creds(self):
        with self.assertRaises(ValueError):
            self.uploader.workshop_backend.build_steamcmd_command(
                exe="steamcmd.exe",
                user="",
                pwd="secret",
                vdf="upload.vdf",
                use_cached=False,
                guard_code="",
            )

    def test_content_fixer_builds_upload_plan_prompt(self):
        fixer = ContentFixer()
        prompt = fixer.build_upload_plan_prompt(
            item_id="123",
            game_name="BZ98R",
            appid="301650",
            visibility="0 (Public)",
            title="Test Mod",
            content=r"C:\mods\content",
            preview=r"C:\mods\preview.jpg",
            auth_mode="Cached credentials",
            manage_owner="76561198000000001",
            change_note="Initial Release",
        )
        self.assertIn("Upload Plan", prompt)
        self.assertIn("UPDATE (123)", prompt)
        self.assertIn("Cached credentials", prompt)
        self.assertIn("Proceed with upload?", prompt)

    def test_save_config_writes_to_config_path_not_cwd(self):
        self.uploader.config_path = os.path.join(self.test_dir, "uploader_config.json")
        other_cwd = os.path.join(self.test_dir, "othercwd")
        os.makedirs(other_cwd, exist_ok=True)
        original_cwd = os.getcwd()
        try:
            os.chdir(other_cwd)
            self.uploader.steamcmd_path.set("C:\\steamcmd\\steamcmd.exe")
            self.uploader.game_var.set("BZ98R")
            self.uploader.username_var.set("tester")
            self.uploader.manage_identity_var.set("76561198000000001")
            self.uploader.use_cached_creds_var.set(True)
            self.uploader.save_config()
        finally:
            os.chdir(original_cwd)

        self.assertTrue(os.path.exists(self.uploader.config_path))
        self.assertFalse(os.path.exists(os.path.join(other_cwd, "uploader_config.json")))

    def test_load_config_uses_legacy_cwd_fallback(self):
        missing_config_path = os.path.join(self.test_dir, "missing", "uploader_config.json")
        legacy_cwd = os.path.join(self.test_dir, "legacycwd")
        os.makedirs(legacy_cwd, exist_ok=True)
        legacy_config = os.path.join(legacy_cwd, "uploader_config.json")
        with open(legacy_config, "w", encoding="utf-8") as f:
            f.write('{"steamcmd_path": "C:\\\\legacy\\\\steamcmd.exe"}')

        self.uploader.config_path = missing_config_path
        original_cwd = os.getcwd()
        try:
            os.chdir(legacy_cwd)
            config = self.uploader.load_config()
        finally:
            os.chdir(original_cwd)

        self.assertEqual(config["steamcmd_path"], "C:\\legacy\\steamcmd.exe")

    def test_app_file_manager_profile_round_trip(self):
        manager = AppFileManager()
        profile_path = os.path.join(self.test_dir, "profiles", "sample.json")
        payload = {
            "mod_path": "C:\\mods\\sample",
            "title": "Sample",
            "item_id": "123",
        }

        manager.save_profile(profile_path, payload)
        loaded = manager.load_profile(profile_path)

        self.assertEqual(loaded, payload)

    def test_app_file_manager_downloads_and_extracts_steamcmd(self):
        manager = AppFileManager()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("steamcmd.exe", "stub")

        response = MagicMock()
        response.content = buffer.getvalue()

        request_with_retry = MagicMock(return_value=response)
        exe_path = manager.download_steamcmd(self.test_dir, request_with_retry)

        self.assertTrue(os.path.exists(exe_path))
        request_with_retry.assert_called_once()

    def test_upload_preflight_validate_inputs_rejects_missing_username_without_cached_creds(self):
        preflight = UploadPreflight()
        steamcmd_path = os.path.join(self.test_dir, "steamcmd.exe")
        with open(steamcmd_path, "w", encoding="utf-8") as f:
            f.write("exe")

        result = preflight.validate_inputs(
            title="Test Mod",
            description="desc",
            steamcmd_path=steamcmd_path,
            content_path="C:\\mods\\content",
            preview_path="C:\\mods\\preview.jpg",
            username="",
            use_cached_creds=False,
            title_limit=128,
            description_limit=8000,
        )

        self.assertEqual(result, ("Error", "Steam Username is required unless 'USE CACHED CREDENTIALS' is enabled."))

    def test_upload_preflight_builds_relative_safety_rows(self):
        preflight = UploadPreflight()
        mod_dir = os.path.join(self.test_dir, "mod")
        os.makedirs(mod_dir, exist_ok=True)
        odf_path = os.path.join(mod_dir, "test.odf")
        with open(odf_path, "w", encoding="utf-8") as f:
            f.write("[CraftClass]\n")

        rows = preflight.build_safety_rows(
            [(odf_path, "Missing Fields", "Missing: weaponName", 2)],
            mod_dir,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["display_path"], "test.odf")
        self.assertEqual(rows[0]["full_path"], odf_path)

    def test_upload_preflight_writes_upload_vdf(self):
        preflight = UploadPreflight()

        def build_upload_vdf_content(**kwargs):
            return f"vdf:{kwargs['appid']}:{kwargs['publishedfileid']}"

        vdf_path = preflight.write_upload_vdf(
            base_dir=self.test_dir,
            appid="301650",
            publishedfileid="123",
            contentfolder=r"C:\mods\content",
            previewfile=r"C:\mods\preview.jpg",
            visibility="0",
            title="Test Mod",
            description="desc",
            changenote="note",
            build_upload_vdf_content=build_upload_vdf_content,
        )

        self.assertTrue(os.path.exists(vdf_path))
        with open(vdf_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "vdf:301650:123")

    def test_scan_mod_safety_does_not_require_every_allowed_param(self):
        self.uploader.resource_dir = self.test_dir

        with open(os.path.join(self.test_dir, "odfHeaderList.txt"), "w", encoding="utf-8") as f:
            f.write("CraftClass\n")
        with open(os.path.join(self.test_dir, "bzrODFparams.txt"), "w", encoding="utf-8") as f:
            f.write("[CraftClass]\nweaponName\nreloadDelay?\n")
        with open(os.path.join(self.test_dir, "test.odf"), "w", encoding="utf-8") as f:
            f.write("[CraftClass]\nweaponName = \"gun\"\n")

        issues = self.uploader.scan_mod_safety(self.test_dir)
        self.assertFalse(any(issue[1] == "Missing Fields" for issue in issues))

    def test_scan_mod_safety_honors_explicit_required_param_marker(self):
        self.uploader.resource_dir = self.test_dir

        with open(os.path.join(self.test_dir, "odfHeaderList.txt"), "w", encoding="utf-8") as f:
            f.write("CraftClass\n")
        with open(os.path.join(self.test_dir, "bzrODFparams.txt"), "w", encoding="utf-8") as f:
            f.write("[CraftClass]\n!weaponName\nreloadDelay?\n")
        with open(os.path.join(self.test_dir, "test.odf"), "w", encoding="utf-8") as f:
            f.write("[CraftClass]\nreloadDelay = 1\n")

        issues = self.uploader.scan_mod_safety(self.test_dir)
        missing = [issue for issue in issues if issue[1] == "Missing Fields"]
        self.assertEqual(len(missing), 1)
        self.assertIn("weaponname", missing[0][2].lower())

    def test_fingerprint_inventory_changes_when_file_changes(self):
        target = os.path.join(self.test_dir, "test.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("alpha")

        first = self.uploader._fingerprint_inventory(self.uploader._build_mod_inventory(self.test_dir))

        with open(target, "w", encoding="utf-8") as f:
            f.write("beta content")

        second = self.uploader._fingerprint_inventory(self.uploader._build_mod_inventory(self.test_dir))
        self.assertNotEqual(first, second)

    def test_extract_loginusers_accounts_vdf_parser(self):
        vdf_content = """
"users"
{
    "76561198000000001"
    {
        "AccountName" "alpha"
        "PersonaName" "Alpha User"
        "MostRecent" "1"
    }
    "76561198000000002"
    {
        "AccountName" "beta"
        "PersonaName" "Beta User"
        "MostRecent" "0"
    }
}
"""
        vdf_path = os.path.join(self.test_dir, "loginusers.vdf")
        with open(vdf_path, "w", encoding="utf-8") as f:
            f.write(vdf_content)

        accounts = self.uploader._extract_loginusers_accounts(vdf_path)
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]["steamid"], "76561198000000001")
        self.assertEqual(accounts[0]["account_name"], "alpha")
        self.assertEqual(accounts[0]["persona_name"], "Alpha User")

    def test_resolve_steam_id_profile_url(self):
        steam_id = self.uploader.resolve_steam_id("https://steamcommunity.com/profiles/76561198000000001", "dummy")
        self.assertEqual(steam_id, "76561198000000001")

    def test_resolve_steam_id_vanity(self):
        with patch.object(self.uploader.steam_service, "resolve_vanity_to_steamid", return_value="76561198000000009") as resolve_mock:
            steam_id = self.uploader.resolve_steam_id("https://steamcommunity.com/id/grizzly", "dummy")
            self.assertEqual(steam_id, "76561198000000009")
            resolve_mock.assert_called_once()

    def test_use_selected_item_id_for_upload_sets_update_target(self):
        self.uploader.item_id_var = DummyVar("0")
        self.uploader.tree = MagicMock()
        self.uploader.tree.selection.return_value = ["item1"]
        self.uploader.tree.item.return_value = {"values": ["My Mod", "999"]}
        self.uploader.notebook = MagicMock()
        self.uploader.upload_tab = MagicMock()

        ok = self.uploader.use_selected_item_id_for_upload()
        self.assertTrue(ok)
        self.assertEqual(self.uploader.item_id_var.get(), "999")
        self.uploader.notebook.select.assert_called_once()

    def test_start_upload_cached_credentials_does_not_require_username(self):
        sc_path = os.path.join(self.test_dir, "steamcmd.exe")
        with open(sc_path, "w", encoding="utf-8") as f:
            f.write("exe")

        content_dir = os.path.join(self.test_dir, "content")
        os.makedirs(content_dir, exist_ok=True)
        preview_path = os.path.join(self.test_dir, "preview.jpg")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write("img")

        self.uploader.base_dir = self.test_dir
        self.uploader.desc_text = MagicMock()
        self.uploader.desc_text.get.return_value = "desc"

        self.uploader.title_var = DummyVar("Test Mod")
        self.uploader.steamcmd_path = DummyVar(sc_path)
        self.uploader.mod_path = DummyVar(content_dir)
        self.uploader.preview_path = DummyVar(preview_path)
        self.uploader.username_var = DummyVar("")
        self.uploader.password_var = DummyVar("")
        self.uploader.use_cached_creds_var = DummyVar(True)
        self.uploader.visibility_var = DummyVar("0 (Public)")
        self.uploader.item_id_var = DummyVar("0")
        self.uploader.note_var = DummyVar("note")
        self.uploader.game_var = DummyVar("BZ98R")
        self.uploader.manage_identity_var = DummyVar("")

        self.uploader._build_mod_inventory = MagicMock(return_value=[])
        self.uploader._collect_mod_findings = MagicMock(return_value={
            "inventory": [],
            "issues": [],
            "validation_errors": [],
            "validation_warnings": [],
            "trn_line_endings": [],
            "trn_duplicate_headers": [],
            "legacy_files": [],
        })
        self.uploader.show_safety_warning = MagicMock(return_value=True)
        self.uploader.save_config = MagicMock()
        self.uploader._confirm_upload_plan = MagicMock(return_value=True)

        with patch("uploader.threading.Thread") as thread_mock:
            thread_instance = MagicMock()
            thread_mock.return_value = thread_instance
            self.uploader.start_upload()
            thread_mock.assert_called_once()

        uploader.messagebox.showerror.assert_not_called()

if __name__ == '__main__':
    unittest.main()
