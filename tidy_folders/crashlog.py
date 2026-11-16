"""When something unexpected goes wrong, save the details to error.log (next to the settings, in
%APPDATA%\\TidyFolders) so it can be reported, instead of failing silently: the .exe has no console
window, so an error message printed there would never be seen."""
from __future__ import annotations

import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from . import __version__
from .rules import APP_NAME, data_dir

MAX_BYTES = 512_000  # past this, only the newest half of the log is kept


def log_path() -> Path:
    return data_dir() / "error.log"


def write(exc_type, exc, tb, where: str = "") -> Path | None:
    """Add one error to error.log. Returns the log's path, or None if it couldn't be written."""
    try:
        path = log_path()
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.write_bytes(path.read_bytes()[-MAX_BYTES // 2:])
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S}  {APP_NAME} {__version__}  "
                    f"Windows {platform.version()}  ({where or 'unknown'})\n")
            f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        return path
    except Exception:
        return None


def message(path: Path | None) -> str:
    """What to tell the user."""
    text = "Sorry, something went wrong."
    if path:
        text += (f"\n\nThe details were saved to:\n{path}\n\nIf it keeps happening, please send that "
                 "file along with what you were doing.")
    return text


def _show(text: str) -> None:
    """A plain Windows message box: works even before (or without) the app's window."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def install() -> None:
    """Catch errors nothing else catches: at start-up, and in background threads."""
    def on_error(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _show(f"{APP_NAME} couldn't start.\n\n" + message(write(exc_type, exc, tb, "start-up")))

    def on_thread_error(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        write(args.exc_type, args.exc_value, args.exc_traceback, f"background: {name}")

    sys.excepthook = on_error
    threading.excepthook = on_thread_error
