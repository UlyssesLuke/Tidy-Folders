"""The small Tidy Folders icon in the notification area (next to the clock)."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

try:
    import pystray
    from PIL import Image
except ImportError:  # running from source without the extra packages: no tray
    pystray = None

from .rules import APP_NAME


def available() -> bool:
    return pystray is not None


class TrayIcon:
    """Left-click opens the window; right-click shows the menu.

    The callbacks run on the tray's own thread, so the window passes in
    functions that hand the work over to the UI thread.
    """

    def __init__(self, icon_path: Path, *, on_open: Callable[[], None],
                 on_sort_now: Callable[[], None], on_toggle_auto: Callable[[], None],
                 is_auto_on: Callable[[], bool], on_quit: Callable[[], None]):
        image = Image.open(icon_path)
        image.load()
        menu = pystray.Menu(
            pystray.MenuItem(f"Open {APP_NAME}", lambda: on_open(), default=True),
            pystray.MenuItem("Sort now", lambda: on_sort_now()),
            pystray.MenuItem("Automatic sorting", lambda: on_toggle_auto(),
                             checked=lambda item: is_auto_on()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: on_quit()),
        )
        self._icon = pystray.Icon("TidyFolders", image, APP_NAME, menu)
        self._thread = threading.Thread(target=self._icon.run, name="tidy-tray", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass

    def notify(self, message: str, title: str = APP_NAME) -> None:
        """Show a Windows notification coming from the tray icon."""
        try:
            self._icon.notify(message[:250], title)
        except Exception:
            pass

    def set_tooltip(self, text: str) -> None:
        try:
            self._icon.title = text[:127]
        except Exception:
            pass

    def refresh_menu(self) -> None:
        """Re-read the tick next to "Automatic sorting"."""
        try:
            self._icon.update_menu()
        except Exception:
            pass
