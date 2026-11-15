"""Settings and the default category rules for Tidy Folders."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "Tidy Folders"

# Each category becomes a folder; files are matched by extension.
# If an extension appears in two categories, the first one wins.
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Images": ["jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif",
               "svg", "ico", "raw", "cr2", "nef", "arw", "dng", "psd", "ai"],
    "Documents": ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "pages", "tex", "epub", "mobi"],
    "Spreadsheets": ["xls", "xlsx", "xlsm", "ods", "csv", "tsv", "numbers"],
    "Presentations": ["ppt", "pptx", "odp", "key"],
    "Videos": ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "3gp"],
    "Music": ["mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "aiff", "opus", "mid", "midi"],
    "Archives": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "iso", "dmg"],
    "Installers": ["exe", "msi", "msix", "appx", "apk"],
    "Code": ["py", "js", "ts", "html", "css", "json", "xml", "yml", "yaml", "java", "c", "cpp",
             "h", "cs", "go", "rs", "php", "rb", "sh", "ps1", "bat", "cmd", "sql", "ipynb"],
    "Fonts": ["ttf", "otf", "woff", "woff2"],
}

# "type"       -> Downloads\Images\photo.jpg
# "type_month" -> Downloads\Images\2026-11\photo.jpg
# "month"      -> Downloads\2026-11\photo.jpg
MODES = ("type", "type_month", "month")


def default_categories() -> dict[str, list[str]]:
    return {name: list(exts) for name, exts in DEFAULT_CATEGORIES.items()}


def normalize_ext(ext: str) -> str:
    """'*.JPG', '.jpg' and ' jpg ' all become 'jpg'."""
    return str(ext).strip().lower().lstrip("*").lstrip(".").strip()


def data_dir() -> Path:
    """Where settings and the undo history live (%APPDATA%\\TidyFolders)."""
    override = os.environ.get("TIDY_FOLDERS_HOME")
    if override:
        base = Path(override)
    else:
        base = Path(os.environ.get("APPDATA") or Path.home()) / "TidyFolders"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Settings:
    folders: list[str] = field(default_factory=list)
    categories: dict[str, list[str]] = field(default_factory=default_categories)
    mode: str = "type"
    other_folder: bool = True       # unknown file types go to "Other"
    skip_shortcuts: bool = True     # leave .lnk / .url files where they are
    auto_sort: bool = False
    interval_seconds: int = 30      # how often auto-sort checks the folders
    settle_seconds: int = 60        # files younger than this are left alone
    close_to_tray: bool = True      # closing the window hides it to the tray
    tray_hint_shown: bool = False   # "still running here" notice shown once

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        s = cls()
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(s, key, value)
        if s.mode not in MODES:
            s.mode = "type"
        s.folders = [str(f) for f in s.folders if isinstance(f, str)] if isinstance(s.folders, list) else []
        if not isinstance(s.categories, dict) or not s.categories:
            s.categories = default_categories()
        s.categories = {
            str(name): [e for e in (normalize_ext(x) for x in exts) if e]
            for name, exts in s.categories.items() if isinstance(exts, list)
        }
        try:
            s.interval_seconds = max(5, int(s.interval_seconds))
            s.settle_seconds = max(0, int(s.settle_seconds))
        except (TypeError, ValueError):
            s.interval_seconds, s.settle_seconds = 30, 60
        return s


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))  # tolerate a BOM
        if isinstance(data, dict):
            return Settings.from_dict(data)
    except (OSError, ValueError):
        pass
    return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = Path(path or settings_path())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic: never leaves a half-written settings file
