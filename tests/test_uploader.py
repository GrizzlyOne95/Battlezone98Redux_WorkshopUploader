import sys
import unittest
from unittest.mock import MagicMock
import os
import tempfile
import shutil

# Mock out GUI and network libraries that might fail in a headless test environment
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.ttk'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['ctypes'] = MagicMock()

# Add parent directory to path to import uploader
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import uploader

class TestWorkshopUploader(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for file operations
        self.test_dir = tempfile.mkdtemp()

        # Instantiate the uploader with a mocked root
        mock_root = MagicMock()
        self.uploader = uploader.WorkshopUploader(mock_root)

        # Redirect log to not pollute stdout during tests
        self.uploader.log = MagicMock()

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

    def test_scan_trn_safety_edge_cases(self):
        """Test scan_trn_safety handles CR without LF, case variations, and unreadable files."""
        # 1. CR without LF
        bad_le_file_r = os.path.join(self.test_dir, "bad_le_r.trn")
        with open(bad_le_file_r, "wb") as f:
            f.write(b"[Size]\rTileSize=8\r")

        # 2. Case insensitive duplicate [Size] headers
        dup_size_case = os.path.join(self.test_dir, "dup_size_case.trn")
        with open(dup_size_case, "wb") as f:
            f.write(b"[size]\r\nTileSize=8\r\n[SIZE]\r\nTileSize=16\r\n")

        # 3. Unreadable file exception (mocking open to throw an exception for a specific file)
        unreadable_file = os.path.join(self.test_dir, "unreadable.trn")
        with open(unreadable_file, "wb") as f:
            f.write(b"dummy")

        # Ensure good file is parsed fine
        good_trn_file = os.path.join(self.test_dir, "good_edge.trn")
        with open(good_trn_file, "wb") as f:
            f.write(b"[Size]\r\nTileSize=8\r\n")

        # Mock builtins.open to throw an exception only for "unreadable.trn"
        import builtins
        original_open = builtins.open
        def mocked_open(file, *args, **kwargs):
            if file == unreadable_file:
                raise PermissionError(f"Permission denied: '{file}'")
            return original_open(file, *args, **kwargs)

        import unittest.mock
        with unittest.mock.patch('builtins.open', side_effect=mocked_open):
            le_issues, dup_issues = self.uploader.scan_trn_safety(self.test_dir)

        self.assertIn(bad_le_file_r, le_issues)
        self.assertIn(dup_size_case, dup_issues)

        # Verify exception block behavior via log
        self.uploader.log.assert_called()
        log_calls = self.uploader.log.call_args_list
        unreadable_logged = any(
            "Could not scan TRN unreadable.trn" in call.args[0]
            for call in log_calls
            if call.args
        )
        self.assertTrue(unreadable_logged, "Exception log for unreadable file was not called")

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

if __name__ == '__main__':
    unittest.main()
