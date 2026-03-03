import sys
import os
import unittest
from unittest.mock import MagicMock
import tempfile

# Mocking modules before importing uploader to prevent headless import errors
from unittest.mock import MagicMock

sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.ttk'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['keyring'] = MagicMock()

import uploader

print("uploader imported successfully!")
