"""Tell File Explorer that the .exe's icon changed, so it redraws it instead of a cached old one.

Windows Explorer remembers icons it has already drawn. After a rebuild the .exe has the
new logo, but open Explorer windows can keep showing the old one. This sends the same
"icons changed" notices that installers send. Nothing is restarted or closed.

Usage:  python packaging/refresh_icon.py "dist/Tidy Folders.exe"      (build.bat runs this)
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

SHCNE_UPDATEITEM = 0x00002000
SHCNE_UPDATEIMAGE = 0x00008000
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST, SHCNF_DWORD, SHCNF_PATHW, SHCNF_FLUSH = 0x0000, 0x0003, 0x0005, 0x1000
SHGFI_SYSICONINDEX = 0x4000


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HANDLE), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]


def refresh(path: str) -> None:
    shell32 = ctypes.windll.shell32
    shell32.SHChangeNotify.argtypes = (wintypes.LONG, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p)
    info = SHFILEINFOW()
    shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info), SHGFI_SYSICONINDEX)
    shell32.SHChangeNotify(SHCNE_UPDATEIMAGE, SHCNF_DWORD | SHCNF_FLUSH, info.iIcon, None)
    shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH, ctypes.c_wchar_p(path), None)
    shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH, None, None)


if __name__ == "__main__":
    if sys.platform == "win32" and len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        refresh(str(Path(sys.argv[1]).resolve()))
        print("Asked File Explorer to redraw the icon for", sys.argv[1])
