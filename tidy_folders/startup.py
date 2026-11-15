"""Start Tidy Folders when you sign in to Windows.

Uses the per-user "Run" list (no admin rights needed). It's the same list shown
in Windows Settings > Apps > Startup, where it can also be switched off.
"""
from __future__ import annotations

import sys

try:
    import winreg
except ImportError:  # not Windows
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Tidy Folders"


def supported() -> bool:
    """Only the .exe can register itself (a source checkout has no single program to start)."""
    return winreg is not None and bool(getattr(sys, "frozen", False))


def command() -> str:
    """What Windows runs at sign-in: this .exe, opening straight into the tray."""
    return f'"{sys.executable}" --tray'


def current_command() -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def is_enabled() -> bool:
    return current_command() is not None


def enable(cmd: str | None = None) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd or command())


def disable() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass  # already off


def refresh_path() -> None:
    """If start-up is on but the .exe has been moved, point Windows at its new location."""
    if supported() and is_enabled() and current_command() != command():
        enable()
