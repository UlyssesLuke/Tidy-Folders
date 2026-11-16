"""Shared bits for the click-through checks in this folder.

Each check works in a fresh temporary folder (its sample files and its own settings), so your real
settings and files are never touched. Screenshots are saved in tests/gui/shots (not kept in git).
"""
from __future__ import annotations

import atexit
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SHOTS = Path(__file__).resolve().parent / "shots"
sys.path.insert(0, str(PROJECT))

_app = None


def setup(name: str) -> Path:
    """A fresh, empty work folder for this check. Settings go inside it, never the real ones."""
    work = Path(tempfile.mkdtemp(prefix=f"tidy-check-{name}-"))
    os.environ["TIDY_FOLDERS_HOME"] = str(work / "appdata")
    atexit.register(shutil.rmtree, work, ignore_errors=True)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # same as the real app: true pixel sizes
    except Exception:
        pass
    return work


def make(folder: Path, names, days_old: int = 10) -> None:
    """Create sample files, dated `days_old` days ago (so auto-sort doesn't wait for them)."""
    stamp = time.time() - days_old * 24 * 3600
    for name in names:
        p = Path(folder) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("sample")
        os.utime(p, (stamp, stamp))


def use(app):
    """Remember the app window the helpers below act on."""
    global _app
    _app = app
    return app


def pump(seconds: float = 0.5) -> None:
    """Let the window run for a moment (draw, handle timers)."""
    end = time.time() + seconds
    while time.time() < end:
        _app.update()
        time.sleep(0.03)


def wait_idle(timeout: float = 10) -> None:
    """Wait for a Tidy up! or Undo to finish."""
    end = time.time() + timeout
    while _app.busy and time.time() < end:
        pump(0.1)
    pump(0.4)


def labels(widget) -> list:
    import tkinter as tk
    out = []
    for w in widget.winfo_children():
        if isinstance(w, tk.Label):
            out.append(w)
        out += labels(w)
    return out


def texts(widget=None) -> list[str]:
    """The text of every label you can see in `widget` (the Sort page's panel by default)."""
    return [str(w.cget("text")) for w in labels(widget or _app.panel) if w.winfo_ismapped()]


def find(text: str, widget=None):
    """The label showing exactly `text`, or None."""
    return next((w for w in labels(widget or _app.panel) if w.cget("text") == text), None)


def click(widget, settle: float = 0.5) -> None:
    widget.event_generate("<Button-1>")
    pump(settle)


def shot(name: str, widget=None, folder: Path = SHOTS) -> None:
    """Save a screenshot of the window (or a dialog) to tests/gui/shots/<name> (or `folder`)."""
    w = widget or _app
    _app.attributes("-topmost", True)
    if w is not _app:
        w.attributes("-topmost", True)
        w.lift()
    pump(0.6)
    folder.mkdir(parents=True, exist_ok=True)
    x, y, width, height = w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()
    ps = f"""Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class Dpi {{ [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }}'
[Dpi]::SetProcessDPIAware() | Out-Null
$b = New-Object System.Drawing.Bitmap {width}, {height}
[System.Drawing.Graphics]::FromImage($b).CopyFromScreen({x}, {y}, 0, 0, $b.Size)
$b.Save('{folder / name}', [System.Drawing.Imaging.ImageFormat]::Png)"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    _app.attributes("-topmost", False)


def check(label: str, ok) -> None:
    print(("PASS  " if ok else "FAIL  ") + label, flush=True)
    if not ok:
        try:
            _app._quit()
        except Exception:
            pass
        raise SystemExit(1)


def finish(name: str) -> None:
    _app._quit()
    print(f"{name} PASSED", flush=True)
