# Double-click this file to open Tidy Folders (no console window).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tidy_folders.gui import main  # noqa: E402

main()
