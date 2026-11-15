"""The sorting engine: decide where each file goes, move it, and undo moves.

Safety rules:
  * Only files directly inside a chosen folder are moved. Existing subfolders
    (and everything in them) are never touched.
  * Nothing is ever deleted or overwritten. Name clashes get " (2)", " (3)"...
  * Every sort is recorded so it can be undone.
  * Hidden/system files, shortcuts, Office lock files and unfinished
    downloads are skipped.

Where a file goes, first match wins:
  1. Course folders: a file whose name contains a course code (ELECTENG101,
     "electeng 101", ELECTENG_101...) goes into the course folder of that name,
     found anywhere inside the chosen folder (years, semesters...).
  2. Code words: a file whose name contains the word goes to that word's folder.
  3. File type: Images, Documents... (or Other).
"""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .rules import Settings, data_dir, normalize_ext

OTHER = "Other"
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
PARTIAL_EXTS = {"crdownload", "part", "partial", "download", "tmp", "temp",
                "opdownload", "!ut", "aria2", "filepart"}
SHORTCUT_EXTS = {"lnk", "url", "website"}
INVALID_NAME_CHARS = set('<>:"/\\|?*')
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                  *(f"LPT{i}" for i in range(1, 10))}

# Only one sort/undo runs at a time, whether from a button or auto-sort.
SORT_LOCK = threading.Lock()


@dataclass
class Move:
    src: str
    dst: str
    category: str
    rule: str = ""  # "course" or "word" when a name rule chose the folder, else ""


# ---------------------------------------------------------------- checks

def extension(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    return ext.lower() if dot and stem else ""


def validate_category_name(name: str) -> str | None:
    """Return an error message if `name` can't be used as a folder name."""
    if not name.strip():
        return "The folder name can't be empty."
    if any(c in INVALID_NAME_CHARS for c in name):
        return 'The folder name can\'t contain any of these: < > : " / \\ | ? *'
    if name != name.strip() or name.endswith("."):
        return "The folder name can't start or end with a space, or end with a dot."
    if name.upper() in RESERVED_NAMES:
        return f'"{name}" is a name Windows reserves. Please choose another.'
    return None


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def folder_problem(folder: str | Path) -> str | None:
    """Return a reason why sorting `folder` would be unsafe, or None if it's fine."""
    p = Path(folder)
    if not p.exists():
        return "This folder doesn't exist (anymore)."
    if not p.is_dir():
        return "This isn't a folder."
    return _protection_problem(p.resolve())


def target_problem(folder: str | Path) -> str | None:
    """Why a name rule can't send files to `folder` (which may not exist yet), or None."""
    p = Path(folder)
    if p.exists() and not p.is_dir():
        return "That's a file, not a folder."
    try:
        p = p.resolve()
    except OSError:
        return "That folder can't be reached."
    return _protection_problem(p)


def _protection_problem(p: Path) -> str | None:
    if p == Path(p.anchor):
        return "Sorting a whole drive isn't allowed. Pick a specific folder, like Downloads."
    if p == Path.home().resolve():
        return ("Sorting your whole user folder isn't allowed. "
                "Pick a folder inside it, like Downloads, Desktop or Documents.")
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
        value = os.environ.get(var)
        if value and _is_within(p, Path(value).resolve()):
            return "This is a system or program folder. Moving files in it could break programs."
    temp = Path(tempfile.gettempdir()).resolve()
    for var in ("APPDATA", "LOCALAPPDATA"):
        value = os.environ.get(var)
        if not value:
            continue
        root = Path(value).resolve()
        inside_temp = _is_within(p, temp) and p != temp
        if (_is_within(p, root) or p == root.parent) and not inside_temp:
            return "This is where programs keep their own data. Moving files in it could break programs."
    return None


def _should_skip(name: str, st: os.stat_result, settings: Settings,
                 siblings: set[str], now: float, min_age: float) -> bool:
    low = name.lower()
    if low in SKIP_NAMES or name.startswith(".") or name.startswith("~$"):
        return True
    ext = extension(name)
    if ext in PARTIAL_EXTS:
        return True
    # Firefox/Chrome keep "file.zip" next to "file.zip.part" while downloading.
    if any(f"{low}.{p}" in siblings for p in PARTIAL_EXTS):
        return True
    if settings.skip_shortcuts and ext in SHORTCUT_EXTS:
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
        return True
    if min_age and now - st.st_mtime < min_age:
        return True
    return False


# ---------------------------------------------------------------- name rules

@dataclass
class NameRule:
    pattern: re.Pattern
    folder: Path
    label: str
    kind: str  # "course" | "word"


def code_pattern(text: str) -> re.Pattern | None:
    """Match `text` inside a file name, ignoring capitals, spaces, dashes, dots and underscores.

    "ELECTENG 101" matches ELECTENG101, electeng_101 and ElectEng-101, but not
    ELECTENG1010 (a different number) or XELECTENG101 (part of another word).
    """
    chars = [c for c in text if c.isalnum()]
    if len(chars) < 3:
        return None
    body = r"[\s_.\-]*".join(re.escape(c) for c in chars)
    tail = r"(?!\d)" if chars[-1].isdigit() else ""
    return re.compile(r"(?<![A-Za-z0-9])" + body + tail, re.IGNORECASE)


# A course folder's name starts with a course code: letters, then 3 or 4 digits (and maybe one
# more letter), e.g. "ELECTENG 101", "COMPSCI101", "MATHS 108G", "ELECTENG 101 - Circuits".
# "2026", "Sem 2", "Semester 2", "Assignment 3" and "Notes" are not course folders.
_COURSE_CODE = re.compile(r"^\s*([A-Za-z]{2,10})[\s_\-]?(\d{3,4})([A-Za-z]?)(?=$|[\s_\-.(\[])")
COURSE_SEARCH_DEPTH = 5          # how many folders deep to look inside a course root
_course_cache: dict[str, tuple[float, list[Path]]] = {}


def course_code(name: str) -> str | None:
    """'ELECTENG 101 - Circuits' -> 'ELECTENG101'; None if the name isn't a course folder."""
    m = _COURSE_CODE.match(name)
    return (m.group(1) + m.group(2) + m.group(3)).upper() if m else None


def clear_course_cache() -> None:
    _course_cache.clear()


def course_folders(root: str | Path) -> list[Path]:
    """Every course folder inside `root`, at any depth (years, semesters...), up to 5 folders deep.

    It doesn't look inside a course folder itself, so "ELECTENG 101\\Lab 1" is never a course.
    Results are remembered for 15 seconds, so newly made course folders show up quickly.
    """
    key = str(root)
    now = time.monotonic()
    cached = _course_cache.get(key)
    if cached and now - cached[0] < 15:
        return cached[1]
    found: list[Path] = []

    def walk(folder: str, depth: int) -> None:
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            try:
                if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if course_code(entry.name):
                found.append(Path(entry.path))
            elif depth < COURSE_SEARCH_DEPTH:
                walk(entry.path, depth + 1)

    walk(str(root), 1)
    _course_cache[key] = (now, found)
    return found


def _newest_first(path: Path) -> list:
    """Sort key so '2027\\Sem 1' comes before '2026\\Sem 2', which comes before '2026\\Sem 1'."""
    return [(1, int(t)) if t.isdigit() else (0, t.lower()) for t in re.split(r"(\d+)", str(path))]


def build_name_rules(settings: Settings) -> list[NameRule]:
    rules: list[NameRule] = []
    seen: set[str] = set()
    for root in settings.course_roots:
        # If a course appears in more than one place (a retake, say), the newest year/semester wins.
        for sub in sorted(course_folders(root), key=_newest_first, reverse=True):
            code = course_code(sub.name)
            pattern = code_pattern(code) if code else None
            if pattern and code not in seen:
                seen.add(code)
                rules.append(NameRule(pattern, sub, sub.name, "course"))
    for rule in settings.keyword_rules:
        pattern = code_pattern(rule["word"])
        if pattern:
            rules.append(NameRule(pattern, Path(rule["folder"]), rule["word"], "word"))
    return rules


def match_name_rule(name: str, rules: list[NameRule]) -> NameRule | None:
    stem = Path(name).stem
    return next((r for r in rules if r.pattern.search(stem)), None)


# ---------------------------------------------------------------- planning

def build_extension_map(categories: dict[str, list[str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name, exts in categories.items():
        for ext in exts:
            mapping.setdefault(normalize_ext(ext), name)
    return mapping


def subfolder_for(category: str, mtime: float, mode: str) -> Path:
    month = datetime.fromtimestamp(mtime).strftime("%Y-%m")
    if mode == "month":
        return Path(month)
    if mode == "type_month":
        return Path(category) / month
    return Path(category)


def unique_destination(path: Path, reserved: set[str]) -> Path:
    """`path` if it's free, otherwise 'name (2).ext', 'name (3).ext', ..."""
    candidate, n = path, 2
    while candidate.exists() or str(candidate).lower() in reserved:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    reserved.add(str(candidate).lower())
    return candidate


def plan_sort(folder: str | Path, settings: Settings,
              min_age: float = 0, now: float | None = None) -> list[Move]:
    """Work out where every loose file in `folder` should go. Moves nothing."""
    folder = Path(folder)
    now = time.time() if now is None else now
    ext_map = build_extension_map(settings.categories)
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    siblings = {e.name.lower() for e in entries}
    reserved: set[str] = set()
    moves: list[Move] = []
    rules = build_name_rules(settings)
    blocked: dict[Path, bool] = {}  # rule folders that are unsafe, or the folder being sorted itself
    try:
        here = folder.resolve()
    except OSError:
        here = folder

    for entry in sorted(entries, key=lambda e: e.name.lower()):
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            st = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if _should_skip(entry.name, st, settings, siblings, now, min_age):
            continue

        rule = match_name_rule(entry.name, rules)
        if rule is not None:
            if rule.folder not in blocked:
                try:
                    same = rule.folder.resolve() == here
                except OSError:
                    same = False
                blocked[rule.folder] = same or target_problem(rule.folder) is not None
            if blocked[rule.folder]:
                continue  # already where it belongs, or the rule points somewhere unsafe: leave it
            dst = unique_destination(rule.folder / entry.name, reserved)
            moves.append(Move(entry.path, str(dst), rule.label, rule.kind))
            continue

        category = ext_map.get(extension(entry.name))
        if category is None:
            if settings.mode != "month" and not settings.other_folder:
                continue
            category = OTHER

        sub = subfolder_for(category, st.st_mtime, settings.mode)
        # Never put a file into a subfolder named like the folder it's already in
        # (e.g. sorting "Downloads\Images" must not create "Images\Images").
        if sub.parts[0].lower() == folder.name.lower():
            continue
        dst = unique_destination(folder / sub / entry.name, reserved)
        moves.append(Move(entry.path, str(dst), category))
    return moves


# ---------------------------------------------------------------- moving

def describe_error(err: OSError) -> str:
    if isinstance(err, PermissionError):
        return "it's open in another program, or you don't have permission to move it"
    if isinstance(err, FileNotFoundError):
        return "it's no longer there"
    return err.strerror or str(err)


def _is_cross_drive(err: OSError) -> bool:
    return getattr(err, "winerror", None) == 17 or err.errno == errno.EXDEV  # ERROR_NOT_SAME_DEVICE


def _move_file(src: Path, dst: Path) -> None:
    """Rename (instant) when possible; copy then delete when the folders are on different drives.

    Never overwrites: fails if `dst` exists. If the original can't be removed after
    copying, the copy is removed again so the file isn't left in two places.
    """
    if dst.exists():
        raise FileExistsError(errno.EEXIST, "a file with that name is already there", str(dst))
    try:
        os.rename(src, dst)
    except OSError as e:
        if not _is_cross_drive(e):
            raise
        shutil.copy2(src, dst)
        try:
            os.remove(src)
        except OSError:
            try:
                os.remove(dst)
            except OSError:
                pass
            raise


def _make_dirs(path: Path, created: list[str]) -> None:
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for d in reversed(missing):
        d.mkdir()
        created.append(str(d))


def apply_moves(moves: list[Move], folder: str | Path, source: str = "manual",
                history: "History | None" = None,
                batch: str | None = None) -> tuple[dict, list[str]]:
    """Move the files. Returns (run record, list of problems).

    Runs sharing a `batch` id (one click of "Sort now" across several folders)
    are undone together by "Undo last sort".
    """
    done: list[dict] = []
    errors: list[str] = []
    created: list[str] = []
    with SORT_LOCK:
        for m in moves:
            src, dst = Path(m.src), Path(m.dst)
            try:
                if not src.exists():
                    errors.append(f"{src.name}: it's no longer there")
                    continue
                _make_dirs(dst.parent, created)
                if dst.exists():  # something appeared since the plan was made
                    dst = unique_destination(dst, set())
                _move_file(src, dst)
                done.append({"src": str(src), "dst": str(dst), "category": m.category, "rule": m.rule})
            except OSError as e:
                errors.append(f"{src.name}: {describe_error(e)}")
        # Drop any folder we made that ended up empty (its file couldn't move).
        for d in sorted(created, key=len, reverse=True):
            try:
                os.rmdir(d)
                created.remove(d)
            except OSError:
                pass

    run_id = uuid.uuid4().hex[:12]
    run = {
        "id": run_id,
        "batch": batch or run_id,
        "time": datetime.now().isoformat(timespec="seconds"),
        "folder": str(folder),
        "source": source,
        "moves": done,
        "created_dirs": created,
        "undone": False,
    }
    if done and history is not None:
        history.add(run)
    return run, errors


def undo_run(run: dict) -> tuple[int, list[str]]:
    """Put every file from `run` back. Returns (files restored, problems)."""
    restored, problems = 0, []
    with SORT_LOCK:
        for m in reversed(run.get("moves", [])):
            src, dst = Path(m["src"]), Path(m["dst"])
            if not dst.exists():
                problems.append(f"{dst.name}: not in \"{dst.parent.name}\" anymore "
                                "(moved, renamed or deleted since)")
                continue
            target = src
            if target.exists():
                target = unique_destination(src, set())
                problems.append(f"{src.name}: another file now has that name, "
                                f"so it came back as \"{target.name}\"")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                _move_file(dst, target)
                restored += 1
            except OSError as e:
                problems.append(f"{dst.name}: {describe_error(e)}")
        # Remove folders this sort created, but only if they're empty now.
        for d in sorted(run.get("created_dirs", []), key=len, reverse=True):
            try:
                os.rmdir(d)
            except OSError:
                pass
    return restored, problems


# ---------------------------------------------------------------- history

class History:
    """Every sort, saved to history.json so it can be undone later."""

    MAX_RUNS = 200

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_dir() / "history.json"
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))  # tolerate a BOM
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _write(self, runs: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(runs, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def runs(self) -> list[dict]:
        with self._lock:
            return self._read()

    def add(self, run: dict) -> None:
        with self._lock:
            runs = self._read()
            runs.append(run)
            self._write(runs[-self.MAX_RUNS:])

    def get(self, run_id: str) -> dict | None:
        return next((r for r in self.runs() if r.get("id") == run_id), None)

    def latest_undoable(self) -> dict | None:
        return next((r for r in reversed(self.runs()) if not r.get("undone")), None)

    def latest_undoable_batch(self) -> list[dict]:
        """All not-yet-undone runs from the most recent sort (may span several folders)."""
        latest = self.latest_undoable()
        if latest is None:
            return []
        batch = latest.get("batch", latest["id"])
        return [r for r in self.runs()
                if r.get("batch", r["id"]) == batch and not r.get("undone")]

    def mark_undone(self, run_id: str) -> None:
        with self._lock:
            runs = self._read()
            for r in runs:
                if r.get("id") == run_id:
                    r["undone"] = True
            self._write(runs)
