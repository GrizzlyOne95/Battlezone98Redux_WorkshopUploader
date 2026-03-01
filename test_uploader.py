import sys
import os
import unittest
from unittest.mock import MagicMock
import tempfile

# Mocking modules before importing uploader to prevent headless import errors
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.ttk'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['requests'] = MagicMock()

import uploader

class TestUploader(unittest.TestCase):
    def setUp(self):
        # Create a mock instance of WorkshopUploader
        self.uploader = uploader.WorkshopUploader.__new__(uploader.WorkshopUploader)
        self.uploader.log = MagicMock()

        # Create a temporary directory for test files
        self.test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.test_dir.cleanup()

    def test_fix_trn_files_lf_to_crlf(self):
        # Setup
        file_path = os.path.join(self.test_dir.name, "test_lf.trn")
        with open(file_path, 'wb') as f:
            f.write(b"Line 1\nLine 2\nLine 3")

        # Execute
        count = self.uploader.fix_trn_files([file_path])

        # Verify
        self.assertEqual(count, 1)
        with open(file_path, 'rb') as f:
            content = f.read()
        self.assertEqual(content, b"Line 1\r\nLine 2\r\nLine 3")

    def test_fix_trn_files_cr_to_crlf(self):
        file_path = os.path.join(self.test_dir.name, "test_cr.trn")
        with open(file_path, 'wb') as f:
            f.write(b"Line 1\rLine 2\rLine 3")

        count = self.uploader.fix_trn_files([file_path])

        self.assertEqual(count, 1)
        with open(file_path, 'rb') as f:
            content = f.read()
        self.assertEqual(content, b"Line 1\r\nLine 2\r\nLine 3")

    def test_fix_trn_files_crlf_unchanged(self):
        file_path = os.path.join(self.test_dir.name, "test_crlf.trn")
        with open(file_path, 'wb') as f:
            f.write(b"Line 1\r\nLine 2\r\nLine 3")

        count = self.uploader.fix_trn_files([file_path])

        self.assertEqual(count, 1)
        with open(file_path, 'rb') as f:
            content = f.read()
        self.assertEqual(content, b"Line 1\r\nLine 2\r\nLine 3")

    def test_fix_trn_files_mixed_endings(self):
        file_path = os.path.join(self.test_dir.name, "test_mixed.trn")
        with open(file_path, 'wb') as f:
            f.write(b"Line 1\nLine 2\rLine 3\r\nLine 4")

        count = self.uploader.fix_trn_files([file_path])

        self.assertEqual(count, 1)
        with open(file_path, 'rb') as f:
            content = f.read()
        self.assertEqual(content, b"Line 1\r\nLine 2\r\nLine 3\r\nLine 4")

    def test_fix_trn_files_multiple_files(self):
        file1 = os.path.join(self.test_dir.name, "test1.trn")
        file2 = os.path.join(self.test_dir.name, "test2.trn")
        with open(file1, 'wb') as f: f.write(b"1\n2")
        with open(file2, 'wb') as f: f.write(b"3\n4")

        count = self.uploader.fix_trn_files([file1, file2])
        self.assertEqual(count, 2)

        with open(file1, 'rb') as f: self.assertEqual(f.read(), b"1\r\n2")
        with open(file2, 'rb') as f: self.assertEqual(f.read(), b"3\r\n4")

    def test_fix_trn_files_error_handling(self):
        non_existent_file = os.path.join(self.test_dir.name, "non_existent.trn")

        count = self.uploader.fix_trn_files([non_existent_file])

        self.assertEqual(count, 0)
        self.uploader.log.assert_called_once()
        args = self.uploader.log.call_args[0][0]
        self.assertTrue(args.startswith(f"Error fixing {non_existent_file}:"))

    def test_fix_trn_files_empty_file(self):
        file_path = os.path.join(self.test_dir.name, "empty.trn")
        with open(file_path, 'wb') as f:
            f.write(b"")

        count = self.uploader.fix_trn_files([file_path])

        self.assertEqual(count, 1)
        with open(file_path, 'rb') as f:
            content = f.read()
        self.assertEqual(content, b"")

if __name__ == '__main__':
    unittest.main()
