import sys
import os
import time
import tempfile
import shutil
from unittest.mock import MagicMock

sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.ttk'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['ctypes'] = MagicMock()

import uploader

def main():
    # Setup test dir
    test_dir = tempfile.mkdtemp()

    try:
        # Create many fake files
        num_files = 100
        num_issues_per_file = 200
        issues = []

        for i in range(num_files):
            file_path = os.path.join(test_dir, f"file_{i}.txt")

            # Write lines to file
            lines = [f"weaponMask = 00000\n" for _ in range(num_issues_per_file)]
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            # Create issues for each line
            for j in range(num_issues_per_file):
                issues.append((file_path, "Crash Risk", "weaponMask=00000", j + 1))

        # Time the function
        mock_root = MagicMock()
        up = uploader.WorkshopUploader(mock_root)
        up.log = MagicMock()

        start_time = time.time()
        count = up.apply_quick_fixes(issues)
        end_time = time.time()

        print(f"Fixed {count} issues in {end_time - start_time:.4f} seconds")

    finally:
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    main()
