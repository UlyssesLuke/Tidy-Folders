"""The Tidy Folders window."""
from __future__ import annotations

import os
import queue
import re
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import engine, startup
from . import tray as tray_mod
from .rules import APP_NAME, default_categories, load_settings, normalize_ext, save_settings
from .watcher import AutoSorter

SHOW_EVENT_NAME = "Local\\TidyFoldersShowWindow"  # a 2nd launch uses this to say "show yourself"

MODE_LABELS = {
    "type": "File type  (Images, Documents, Music...)",
    "type_month": "File type, then month  (Images \\ 2026-11)",
    "month": "Month only  (2026-11)",
}
INTERVALS = [("15 seconds", 15), ("30 seconds", 30), ("1 minute", 60),
             ("5 minutes", 300), ("15 minutes", 900)]

_KNOWN_FOLDER_IDS = {
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
}


def known_folder(name: str) -> Path:
    """The real location of Downloads/Desktop/Documents (handles OneDrive and moved folders)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            guid = GUID()
            ctypes.oledll.ole32.CLSIDFromString(_KNOWN_FOLDER_IDS[name], ctypes.byref(guid))
            ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                          ctypes.byref(ptr)) == 0:
                path = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                if path:
                    return Path(path)
        except Exception:
            pass
    return Path.home() / name


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %Y  %I:%M %p")
    except (TypeError, ValueError):
        return str(iso)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class CategoryDialog(tk.Toplevel):
    """Small window for adding or editing one category."""

    def __init__(self, parent: tk.Misc, title: str, validate, name: str = "", exts: str = ""):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result: tuple[str, list[str]] | None = None
        self._validate = validate

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Folder name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=name)
        name_entry = ttk.Entry(body, textvariable=self.name_var, width=40)
        name_entry.grid(row=1, column=0, sticky="we", pady=(2, 10))
        ttk.Label(body, text="File types, separated by commas (for example: jpg, png, gif)"
                  ).grid(row=2, column=0, sticky="w")
        self.exts_var = tk.StringVar(value=exts)
        ttk.Entry(body, textvariable=self.exts_var, width=64).grid(row=3, column=0, sticky="we",
                                                                    pady=(2, 14))
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self._save).pack(side="right", padx=(0, 6))
        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        name_entry.focus_set()
        self.grab_set()
        self.wait_window()

    def _save(self) -> None:
        name = self.name_var.get().strip()
        raw = re.split(r"[,;\s]+", self.exts_var.get())
        exts = list(dict.fromkeys(e for e in (normalize_ext(x) for x in raw) if e))
        error = self._validate(name, exts)
        if error:
            messagebox.showwarning(APP_NAME, error, parent=self)
            return
        self.result = (name, exts)
        self.destroy()


class App(tk.Tk):
    def __init__(self, start_hidden: bool = False) -> None:
        super().__init__()
        if start_hidden:
            self.withdraw()  # opened at sign-in: live in the tray, no window
        self.title(APP_NAME)
        self.icon_path = Path(__file__).resolve().parent / "assets" / "icon.ico"
        if self.icon_path.exists():
            try:
                self.iconbitmap(default=str(self.icon_path))  # window, dialogs and taskbar
            except tk.TclError:
                pass
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96)  # follow Windows display scaling
        self.geometry(f"{self.px(1020)}x{self.px(720)}")
        self.minsize(self.px(800), self.px(580))

        self.settings = load_settings()
        self.history = engine.History()
        self.events: queue.Queue = queue.Queue()  # work for the UI thread
        self.auto: AutoSorter | None = None
        self.busy = False
        self.tray = self._create_tray()

        self._init_style()
        self._build()
        self._refresh_folders()
        self._refresh_categories()
        self._refresh_history()
        if self.settings.auto_sort:
            self._start_auto()
        self._update_auto_label()
        if self.tray:
            self.tray.start()
        elif start_hidden:
            self.deiconify()  # no tray available, so show the window after all
        try:
            startup.refresh_path()  # the .exe may have been moved since start-up was turned on
        except OSError:
            pass
        self._listen_for_show_requests()
        self.after(150, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def px(self, n: float) -> int:
        return int(n * self.scale)

    # ------------------------------------------------------------ layout

    def _init_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=10)
        for name in ("TkTextFont", "TkHeadingFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(size=10)
        family = base.actual("family")
        style.configure("Treeview", rowheight=int(base.metrics("linespace") * 1.6))
        style.configure("Title.TLabel", font=(family, 16, "bold"))
        style.configure("Muted.TLabel", foreground="#5f6368")
        style.configure("Summary.TLabel", font=(family, 10, "bold"))
        style.configure("Primary.TButton", font=(family, 10, "bold"))

    def _build(self) -> None:
        self.status_var = tk.StringVar(value="Ready.")
        status = ttk.Frame(self, padding=(16, 0, 16, 10))
        status.pack(side="bottom", fill="x")
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")

        header = ttk.Frame(self, padding=(16, 14, 16, 0))
        header.pack(side="top", fill="x")
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Sorts loose files into folders. Nothing is deleted, "
                               "and every sort can be undone.",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(6, 0))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=10)
        self.sort_tab = ttk.Frame(self.notebook, padding=12)
        self.cat_tab = ttk.Frame(self.notebook, padding=12)
        self.hist_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.sort_tab, text="   Sort   ")
        self.notebook.add(self.cat_tab, text="   Categories   ")
        self.notebook.add(self.hist_tab, text="   History & undo   ")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._build_sort_tab()
        self._build_categories_tab()
        self._build_history_tab()

    def _build_sort_tab(self) -> None:
        t = self.sort_tab
        t.columnconfigure(0, weight=1)
        t.columnconfigure(1, weight=1)
        t.rowconfigure(2, weight=1)

        # Folders to tidy
        ff = ttk.LabelFrame(t, text="Folders to tidy", padding=10)
        ff.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ff.columnconfigure(0, weight=1)
        self.folder_list = tk.Listbox(ff, height=4, activestyle="none", selectmode="extended",
                                      relief="solid", borderwidth=1, highlightthickness=0,
                                      exportselection=False)
        self.folder_list.grid(row=0, column=0, rowspan=2, sticky="nsew")
        ttk.Button(ff, text="Add folder...", command=self._browse_folder
                   ).grid(row=0, column=1, sticky="new", padx=(8, 0))
        ttk.Button(ff, text="Remove", command=self._remove_folders
                   ).grid(row=1, column=1, sticky="new", padx=(8, 0), pady=(4, 0))
        quick = ttk.Frame(ff)
        quick.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(quick, text="Quick add:").pack(side="left")
        for name in ("Downloads", "Desktop", "Documents"):
            ttk.Button(quick, text=name, command=lambda n=name: self._add_folder(known_folder(n))
                       ).pack(side="left", padx=(6, 0))

        # How to sort
        of = ttk.LabelFrame(t, text="How to sort", padding=10)
        of.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        of.columnconfigure(0, weight=1)
        ttk.Label(of, text="Organize by").grid(row=0, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=MODE_LABELS[self.settings.mode])
        mode_box = ttk.Combobox(of, textvariable=self.mode_var, values=list(MODE_LABELS.values()),
                                state="readonly")
        mode_box.grid(row=1, column=0, sticky="we", pady=(2, 8))
        mode_box.bind("<<ComboboxSelected>>", self._on_options_changed)
        self.other_var = tk.BooleanVar(value=self.settings.other_folder)
        ttk.Checkbutton(of, text='Put files of unknown types in an "Other" folder',
                        variable=self.other_var, command=self._on_options_changed
                        ).grid(row=2, column=0, sticky="w")
        self.shortcut_var = tk.BooleanVar(value=self.settings.skip_shortcuts)
        ttk.Checkbutton(of, text="Leave shortcuts (.lnk, .url) where they are",
                        variable=self.shortcut_var, command=self._on_options_changed
                        ).grid(row=3, column=0, sticky="w", pady=(4, 0))

        # Actions
        bar = ttk.Frame(t)
        bar.grid(row=1, column=0, columnspan=2, sticky="we", pady=(12, 6))
        self.preview_btn = ttk.Button(bar, text="Preview", command=self._preview)
        self.sort_btn = ttk.Button(bar, text="Sort now", style="Primary.TButton",
                                   command=self._sort_now)
        self.undo_btn = ttk.Button(bar, text="Undo last sort", command=self._undo_last)
        for b in (self.preview_btn, self.sort_btn, self.undo_btn):
            b.pack(side="left", padx=(0, 6))
        self.summary_var = tk.StringVar(
            value="Click Preview to see what would move." if self.settings.folders
            else "Add a folder, then click Preview to see what would move.")
        ttk.Label(bar, textvariable=self.summary_var, style="Summary.TLabel"
                  ).pack(side="left", padx=(10, 0))

        # Preview table
        pf = ttk.Frame(t)
        pf.grid(row=2, column=0, columnspan=2, sticky="nsew")
        pf.columnconfigure(0, weight=1)
        pf.rowconfigure(0, weight=1)
        self.preview = ttk.Treeview(pf, columns=("file", "dest", "folder"), show="headings")
        for col, text, width in (("file", "File", 300), ("dest", "Will move to", 360),
                                 ("folder", "In folder", 160)):
            self.preview.heading(col, text=text, anchor="w")
            self.preview.column(col, width=self.px(width), anchor="w")
        ysb = ttk.Scrollbar(pf, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=ysb.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        # Automatic sorting & running in the background
        af = ttk.LabelFrame(t, text="Automatic sorting", padding=10)
        af.grid(row=3, column=0, columnspan=2, sticky="we", pady=(12, 0))
        row = ttk.Frame(af)
        row.pack(fill="x")
        self.auto_var = tk.BooleanVar(value=self.settings.auto_sort)
        ttk.Checkbutton(row, text="Keep these folders tidy automatically, checking every",
                        variable=self.auto_var, command=self._toggle_auto).pack(side="left")
        self.interval_var = tk.StringVar(value=self._interval_label(self.settings.interval_seconds))
        ib = ttk.Combobox(row, textvariable=self.interval_var, values=[l for l, _ in INTERVALS],
                          state="readonly", width=12)
        ib.pack(side="left", padx=6)
        ib.bind("<<ComboboxSelected>>", self._on_interval_changed)
        self.auto_state_var = tk.StringVar()
        ttk.Label(row, textvariable=self.auto_state_var, style="Muted.TLabel"
                  ).pack(side="left", padx=(8, 0))

        exe_only = "   (available in the .exe version)"
        self.startup_var = tk.BooleanVar(value=startup.supported() and startup.is_enabled())
        startup_cb = ttk.Checkbutton(
            af, text="Start Tidy Folders when I sign in to Windows (it opens quietly in the tray)",
            variable=self.startup_var, command=self._toggle_startup)
        startup_cb.pack(anchor="w", pady=(8, 0))
        if not startup.supported():
            startup_cb.configure(text=startup_cb.cget("text") + exe_only)
            startup_cb.state(["disabled"])

        self.tray_var = tk.BooleanVar(value=self.settings.close_to_tray)
        tray_cb = ttk.Checkbutton(
            af, text="When I close this window, keep running in the tray (next to the clock)",
            variable=self.tray_var, command=self._toggle_close_to_tray)
        tray_cb.pack(anchor="w", pady=(4, 0))
        if not self.tray:
            tray_cb.configure(text=tray_cb.cget("text") + exe_only)
            tray_cb.state(["disabled"])

    def _build_categories_tab(self) -> None:
        t = self.cat_tab
        t.columnconfigure(0, weight=1)
        t.rowconfigure(1, weight=1)
        ttk.Label(t, text="Each category becomes a folder. Files are matched by their type: "
                          "the letters after the last dot in the name (photo.jpg is a jpg).",
                  style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.cat_tree = ttk.Treeview(t, columns=("name", "exts"), show="headings",
                                     selectmode="browse")
        self.cat_tree.heading("name", text="Folder name", anchor="w")
        self.cat_tree.column("name", width=self.px(170), stretch=False, anchor="w")
        self.cat_tree.heading("exts", text="File types", anchor="w")
        self.cat_tree.column("exts", width=self.px(600), anchor="w")
        self.cat_tree.grid(row=1, column=0, sticky="nsew")
        self.cat_tree.bind("<Double-1>", lambda e: self._edit_category())
        ysb = ttk.Scrollbar(t, orient="vertical", command=self.cat_tree.yview)
        self.cat_tree.configure(yscrollcommand=ysb.set)
        ysb.grid(row=1, column=1, sticky="ns")
        btns = ttk.Frame(t)
        btns.grid(row=1, column=2, sticky="n", padx=(10, 0))
        for text, cmd in (("Add category...", self._add_category), ("Edit...", self._edit_category),
                          ("Remove", self._remove_category),
                          ("Reset to defaults", self._reset_categories)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=(0, 4))
        ttk.Label(t, text='Files whose type isn\'t listed go into "Other" '
                          "(if that option is on in the Sort tab).",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _build_history_tab(self) -> None:
        t = self.hist_tab
        t.columnconfigure(0, weight=1)
        t.rowconfigure(1, weight=1)
        ttk.Label(t, text="Every sort is listed here. Select one and click Undo to put "
                          "those files back exactly where they were.",
                  style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.hist_tree = ttk.Treeview(t, columns=("when", "folder", "count", "how", "status"),
                                      show="headings", selectmode="browse")
        for col, text, width, stretch in (("when", "When", 190, False), ("folder", "Folder", 360, True),
                                          ("count", "Files moved", 100, False),
                                          ("how", "How", 110, False), ("status", "Status", 110, False)):
            self.hist_tree.heading(col, text=text, anchor="w")
            self.hist_tree.column(col, width=self.px(width), stretch=stretch, anchor="w")
        self.hist_tree.grid(row=1, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(t, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=ysb.set)
        ysb.grid(row=1, column=1, sticky="ns")
        btns = ttk.Frame(t)
        btns.grid(row=1, column=2, sticky="n", padx=(10, 0))
        self.hist_undo_btn = ttk.Button(btns, text="Undo this sort", command=self._undo_selected)
        self.hist_undo_btn.pack(fill="x", pady=(0, 4))
        ttk.Button(btns, text="Open folder", command=self._open_selected_folder
                   ).pack(fill="x", pady=(0, 4))

    # ------------------------------------------------------------ helpers

    def _save(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as e:
            self.status_var.set(f"Couldn't save settings: {e}")
        if self.auto:
            self.auto.update_settings(self.settings)

    def _drain_events(self) -> None:
        """Run callbacks that background threads queued for the UI thread."""
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _run_in_background(self, work, on_done, message: str) -> None:
        self._set_busy(True, message)

        def runner():
            try:
                result = work()
            except Exception as err:  # surface anything unexpected instead of dying silently
                def fail(err=err):
                    self._set_busy(False)
                    messagebox.showerror(APP_NAME, f"Something went wrong:\n\n{err}", parent=self)
                self.events.put(fail)
                return

            def finish():
                self._set_busy(False)
                on_done(result)
            self.events.put(finish)

        threading.Thread(target=runner, daemon=True).start()

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.preview_btn, self.sort_btn, self.undo_btn, self.hist_undo_btn):
            b.configure(state=state)
        self.configure(cursor="watch" if busy else "")
        if message:
            self.status_var.set(message)

    def _show_problems(self, title: str, problems: list[str]) -> None:
        shown = problems[:15]
        extra = f"\n...and {len(problems) - 15} more." if len(problems) > 15 else ""
        messagebox.showwarning(APP_NAME, title + "\n\n" + "\n".join(f"- {p}" for p in shown) + extra,
                               parent=self)

    def _interval_label(self, seconds: int) -> str:
        return next((label for label, s in INTERVALS if s == seconds), f"{seconds} seconds")

    def _on_tab_changed(self, _event=None) -> None:
        if self.notebook.select() == str(self.hist_tab):
            self._refresh_history()

    # ------------------------------------------------------------ folders

    def _refresh_folders(self) -> None:
        self.folder_list.delete(0, "end")
        for f in self.settings.folders:
            self.folder_list.insert("end", f)

    def _browse_folder(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Choose a folder to tidy", mustexist=True)
        if path:
            self._add_folder(Path(path))

    def _add_folder(self, path: Path) -> None:
        path_str = str(Path(path))
        problem = engine.folder_problem(path_str)
        if problem:
            messagebox.showwarning(APP_NAME, f"{path_str}\n\n{problem}", parent=self)
            return
        resolved = Path(path_str).resolve()
        if any(Path(f).resolve() == resolved for f in self.settings.folders):
            self.status_var.set(f"{path_str} is already in the list.")
            return
        if self.auto and not messagebox.askyesno(
                APP_NAME, "Automatic sorting is on, so files in this folder will start being "
                          f"sorted right away.\n\n{path_str}\n\nAdd it?", parent=self):
            return
        self.settings.folders.append(path_str)
        self._save()
        self._refresh_folders()
        self._clear_preview()
        self.status_var.set(f"Added {path_str}. Click Preview to see what would move.")

    def _remove_folders(self) -> None:
        selected = list(self.folder_list.curselection())
        if not selected:
            self.status_var.set("Select a folder in the list first.")
            return
        for i in reversed(selected):
            del self.settings.folders[i]
        self._save()
        self._refresh_folders()
        self._clear_preview()
        self.status_var.set("Removed. Files already sorted stay where they are.")

    # ------------------------------------------------------------ options

    def _on_options_changed(self, *_args) -> None:
        label = self.mode_var.get()
        self.settings.mode = next(k for k, v in MODE_LABELS.items() if v == label)
        self.settings.other_folder = self.other_var.get()
        self.settings.skip_shortcuts = self.shortcut_var.get()
        self._save()
        self._refresh_preview_if_shown()

    # ------------------------------------------------------------ preview & sort

    def _plan_all(self, quiet: bool = False) -> dict[str, list[engine.Move]]:
        plans: dict[str, list[engine.Move]] = {}
        skipped = []
        for folder in self.settings.folders:
            problem = engine.folder_problem(folder)
            if problem:
                skipped.append(f"{folder}: {problem}")
                continue
            moves = engine.plan_sort(folder, self.settings)
            if moves:
                plans[folder] = moves
        if skipped and not quiet:
            self._show_problems("These folders were skipped:", skipped)
        return plans

    def _clear_preview(self) -> None:
        self.preview.delete(*self.preview.get_children())

    def _show_plan(self, plans: dict[str, list[engine.Move]]) -> None:
        self._clear_preview()
        counts: Counter = Counter()
        for folder, moves in plans.items():
            base = Path(folder)
            for m in moves:
                rel = os.path.relpath(m.dst, base)
                self.preview.insert("", "end", values=(Path(m.src).name, rel, base.name))
                counts[m.category] += 1
        total = sum(counts.values())
        if total == 0:
            self.summary_var.set("Nothing to sort. These folders are already tidy.")
            return
        parts = ", ".join(f"{name} {n}" for name, n in counts.most_common(4))
        more = ", ..." if len(counts) > 4 else ""
        self.summary_var.set(f"{plural(total, 'file')} will move:  {parts}{more}")

    def _preview(self) -> dict[str, list[engine.Move]]:
        if not self.settings.folders:
            self.summary_var.set("Add a folder first (try the Downloads button).")
            return {}
        plans = self._plan_all()
        self._show_plan(plans)
        self.status_var.set("Preview only. Nothing has moved yet.")
        return plans

    def _refresh_preview_if_shown(self) -> None:
        if self.preview.get_children():
            self._show_plan(self._plan_all(quiet=True))

    def _sort_now(self) -> None:
        if self.busy:
            return
        plans = self._preview()
        total = sum(len(m) for m in plans.values())
        if total == 0:
            return
        if not messagebox.askyesno(
                APP_NAME, f"Move {plural(total, 'file')} into folders, as shown in the list?\n\n"
                          "Nothing is deleted, and you can undo this afterwards.", parent=self):
            return
        batch = uuid.uuid4().hex[:12]

        def work():
            return [engine.apply_moves(moves, folder, "manual", self.history, batch)
                    for folder, moves in plans.items()]
        self._run_in_background(work, self._after_sort, f"Sorting {plural(total, 'file')}...")

    def _after_sort(self, results, quiet: bool = False) -> None:
        moved = sum(len(run["moves"]) for run, _ in results)
        errors = [e for _, errs in results for e in errs]
        self._clear_preview()
        self._refresh_history()
        self.summary_var.set(f"Done. Moved {plural(moved, 'file')}. "
                             "Changed your mind? Click Undo last sort.")
        self.status_var.set(f"Sorted {plural(moved, 'file')} at {datetime.now():%I:%M %p}.")
        if errors and not quiet:
            self._show_problems(f"Moved {plural(moved, 'file')}, but {len(errors)} "
                                f"couldn't be moved:", errors)

    # ------------------------------------------------------------ undo

    def _undo_last(self) -> None:
        runs = self.history.latest_undoable_batch()
        if not runs:
            messagebox.showinfo(APP_NAME, "There's nothing to undo yet.", parent=self)
            return
        self._confirm_undo(runs)

    def _undo_selected(self) -> None:
        selected = self.hist_tree.selection()
        if not selected:
            self.status_var.set("Select a sort in the list first.")
            return
        run = self.history.get(selected[0])
        if run is None:
            return
        if run.get("undone"):
            messagebox.showinfo(APP_NAME, "That sort has already been undone.", parent=self)
            return
        self._confirm_undo([run])

    def _confirm_undo(self, runs: list[dict]) -> None:
        if self.busy:
            return
        total = sum(len(r["moves"]) for r in runs)
        folders = "\n".join(r["folder"] for r in runs)
        if not messagebox.askyesno(
                APP_NAME, f"Undo the sort from {fmt_time(runs[0]['time'])}?\n\n{folders}\n\n"
                          f"{plural(total, 'file')} will go back to where they were.", parent=self):
            return

        def work():
            restored, problems = 0, []
            for run in runs:
                r, p = engine.undo_run(run)
                self.history.mark_undone(run["id"])
                restored += r
                problems += p
            return restored, problems
        self._run_in_background(work, self._after_undo, "Undoing...")

    def _after_undo(self, result) -> None:
        restored, problems = result
        self._refresh_history()
        self._refresh_preview_if_shown()
        self.summary_var.set(f"Undone. Put {plural(restored, 'file')} back where they were.")
        self.status_var.set(f"Undo finished at {datetime.now():%I:%M %p}.")
        if problems:
            self._show_problems("Undo finished, with some notes:", problems)

    # ------------------------------------------------------------ history

    def _refresh_history(self) -> None:
        selected = self.hist_tree.selection()
        self.hist_tree.delete(*self.hist_tree.get_children())
        for run in reversed(self.history.runs()):
            if "id" not in run:
                continue
            self.hist_tree.insert("", "end", iid=run["id"], values=(
                fmt_time(run.get("time", "")),
                run.get("folder", ""),
                len(run.get("moves", [])),
                "Automatic" if run.get("source") == "auto" else "Sort now",
                "Undone" if run.get("undone") else "Can undo",
            ))
        keep = [s for s in selected if self.hist_tree.exists(s)]
        if keep:
            self.hist_tree.selection_set(keep)

    def _open_selected_folder(self) -> None:
        selected = self.hist_tree.selection()
        run = self.history.get(selected[0]) if selected else None
        if not run:
            self.status_var.set("Select a sort in the list first.")
            return
        if Path(run["folder"]).is_dir() and hasattr(os, "startfile"):
            os.startfile(run["folder"])

    # ------------------------------------------------------------ categories

    def _refresh_categories(self) -> None:
        self.cat_tree.delete(*self.cat_tree.get_children())
        for name, exts in self.settings.categories.items():
            self.cat_tree.insert("", "end", iid=name, values=(name, ", ".join(exts)))

    def _validate_category(self, name: str, exts: list[str], original: str | None = None) -> str | None:
        error = engine.validate_category_name(name)
        if error:
            return error
        if name.lower() == engine.OTHER.lower():
            return '"Other" is used for files of unknown types. Please choose another name.'
        for other in self.settings.categories:
            if other != original and other.lower() == name.lower():
                return f'There\'s already a category called "{other}".'
        if not exts:
            return "Add at least one file type."
        for other, other_exts in self.settings.categories.items():
            if other == original:
                continue
            clash = sorted(set(exts) & set(other_exts))
            if clash:
                verb = "is" if len(clash) == 1 else "are"
                return f'{", ".join(clash)} {verb} already in "{other}". Remove it there first.'
        return None

    def _categories_changed(self, select: str | None = None) -> None:
        self._save()
        self._refresh_categories()
        if select and self.cat_tree.exists(select):
            self.cat_tree.selection_set(select)
            self.cat_tree.see(select)
        self._refresh_preview_if_shown()

    def _add_category(self) -> None:
        dlg = CategoryDialog(self, "Add category", validate=self._validate_category)
        if dlg.result:
            name, exts = dlg.result
            self.settings.categories[name] = exts
            self._categories_changed(select=name)

    def _edit_category(self) -> None:
        selected = self.cat_tree.selection()
        if not selected:
            self.status_var.set("Select a category first.")
            return
        old = selected[0]
        dlg = CategoryDialog(self, "Edit category",
                             validate=lambda n, e: self._validate_category(n, e, original=old),
                             name=old, exts=", ".join(self.settings.categories[old]))
        if dlg.result:
            name, exts = dlg.result
            self.settings.categories = {
                (name if k == old else k): (exts if k == old else v)
                for k, v in self.settings.categories.items()
            }
            self._categories_changed(select=name)

    def _remove_category(self) -> None:
        selected = self.cat_tree.selection()
        if not selected:
            self.status_var.set("Select a category first.")
            return
        name = selected[0]
        if messagebox.askyesno(APP_NAME, f'Remove the "{name}" category?\n\n'
                                         "Files already sorted into that folder stay where they are.",
                               parent=self):
            del self.settings.categories[name]
            self._categories_changed()

    def _reset_categories(self) -> None:
        if messagebox.askyesno(APP_NAME, "Replace your categories with the built-in ones?",
                               parent=self):
            self.settings.categories = default_categories()
            self._categories_changed()

    # ------------------------------------------------------------ automatic sorting

    def _toggle_auto(self) -> None:
        if self.auto_var.get():
            if not messagebox.askyesno(
                    APP_NAME, "Tidy Folders will now sort these folders by itself, without "
                              f"asking first, every {self.interval_var.get()}.\n\n"
                              "It never deletes anything, waits until new files are a minute old "
                              "(so downloads can finish), and every sort can be undone from the "
                              "History tab.\n\nTurn on automatic sorting?", parent=self):
                self.auto_var.set(False)
                return
            self._set_auto(True)
            self._offer_startup()
        else:
            self._set_auto(False)

    def _set_auto(self, on: bool) -> None:
        self.settings.auto_sort = on
        self.auto_var.set(on)
        self._save()
        if on:
            self._start_auto()
        else:
            self._stop_auto()
        self._update_auto_label()
        if self.tray:
            self.tray.refresh_menu()

    def _start_auto(self) -> None:
        if self.auto:
            return

        def on_run(run, errors):  # called from the background thread
            self.events.put(lambda: self._on_auto_run(run, errors))
        self.auto = AutoSorter(self.settings, self.history, on_run)
        self.auto.start()

    def _stop_auto(self) -> None:
        if self.auto:
            self.auto.stop()
            self.auto = None

    def _update_auto_label(self) -> None:
        if not self.auto:
            self.auto_state_var.set("Off.")
        elif self.tray and self.settings.close_to_tray:
            self.auto_state_var.set("On. Keeps working in the tray after you close the window.")
        else:
            self.auto_state_var.set("On. Runs while this window is open.")

    def _on_interval_changed(self, *_args) -> None:
        self.settings.interval_seconds = dict(INTERVALS).get(self.interval_var.get(), 30)
        self._save()

    def _on_auto_run(self, run: dict, errors: list[str]) -> None:
        moved = len(run.get("moves", []))
        if moved:
            where = Path(run["folder"]).name
            self.status_var.set(f"Auto-sorted {plural(moved, 'file')} in {where} "
                                f"at {datetime.now():%I:%M %p}.")
            if self.tray:
                self.tray.set_tooltip(f"{APP_NAME}\nLast sorted {plural(moved, 'file')} "
                                      f"at {datetime.now():%I:%M %p}")
            self._refresh_history()
            self._refresh_preview_if_shown()
        if errors:
            self.status_var.set(f"Auto-sort couldn't move {plural(len(errors), 'file')}: {errors[0]}")

    # ------------------------------------------------------------ start-up & tray

    def _toggle_startup(self) -> None:
        try:
            if self.startup_var.get():
                startup.enable()
                self.status_var.set("Tidy Folders will start by itself when you sign in to Windows.")
            else:
                startup.disable()
                self.status_var.set("Tidy Folders won't start by itself anymore.")
        except OSError as e:
            self.startup_var.set(startup.is_enabled())
            messagebox.showerror(APP_NAME, f"Couldn't change the start-up setting:\n\n{e}", parent=self)

    def _offer_startup(self) -> None:
        """Right after automatic sorting is switched on, offer to make it survive restarts."""
        if not startup.supported() or startup.is_enabled():
            return
        if messagebox.askyesno(
                APP_NAME, "Also start Tidy Folders when you sign in to Windows?\n\n"
                          "It opens quietly in the tray (next to the clock), so your folders "
                          "stay tidy without you having to open it. You can change this anytime "
                          "at the bottom of this window.", parent=self):
            self.startup_var.set(True)
            self._toggle_startup()

    def _toggle_close_to_tray(self) -> None:
        self.settings.close_to_tray = self.tray_var.get()
        self._save()
        self._update_auto_label()

    def _create_tray(self) -> "tray_mod.TrayIcon | None":
        if not tray_mod.available() or not self.icon_path.exists():
            return None

        def on_ui_thread(fn):  # tray clicks arrive on the tray's thread
            return lambda: self.events.put(fn)
        try:
            return tray_mod.TrayIcon(
                self.icon_path,
                on_open=on_ui_thread(self._show_window),
                on_sort_now=on_ui_thread(self._tray_sort_now),
                on_toggle_auto=on_ui_thread(self._tray_toggle_auto),
                is_auto_on=lambda: self.auto is not None,
                on_quit=on_ui_thread(self._quit),
            )
        except Exception:
            return None

    def _show_window(self) -> None:
        self.deiconify()
        if self.state() == "iconic":
            self.state("normal")
        self.lift()
        self.attributes("-topmost", True)  # bring it in front of other windows...
        self.after(300, lambda: self.attributes("-topmost", False))  # ...without pinning it there
        self.focus_force()
        self._refresh_history()

    def _tray_sort_now(self) -> None:
        if self.busy or not self.tray:
            return
        if not self.settings.folders:
            self.tray.notify("No folders to tidy yet. Open Tidy Folders and add one first.")
            return
        plans = self._plan_all(quiet=True)
        total = sum(len(m) for m in plans.values())
        if total == 0:
            self.tray.notify("Nothing to sort. Your folders are already tidy.")
            return
        batch = uuid.uuid4().hex[:12]

        def work():
            return [engine.apply_moves(moves, folder, "manual", self.history, batch)
                    for folder, moves in plans.items()]

        def done(results):
            self._after_sort(results, quiet=True)
            moved = sum(len(run["moves"]) for run, _ in results)
            failed = sum(len(errs) for _, errs in results)
            message = f"Moved {plural(moved, 'file')} into folders."
            if failed:
                message += f" {plural(failed, 'file')} couldn't be moved (open in another program?)."
            self.tray.notify(message + " To undo, open Tidy Folders and click Undo last sort.")
        self._run_in_background(work, done, f"Sorting {plural(total, 'file')}...")

    def _tray_toggle_auto(self) -> None:
        turn_on = self.auto is None
        self._set_auto(turn_on)
        if self.tray:
            self.tray.notify(
                f"Automatic sorting is on. Checking every {self.interval_var.get()}; "
                "new files are left for a minute first." if turn_on
                else "Automatic sorting is off.")

    def _listen_for_show_requests(self) -> None:
        """Opening Tidy Folders again (e.g. from the Start menu) shows this window."""
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                          wintypes.LPCWSTR)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        handle = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        if not handle:
            return

        def wait():
            while kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:  # WAIT_OBJECT_0
                self.events.put(self._show_window)
        threading.Thread(target=wait, name="tidy-show-requests", daemon=True).start()

    def _on_close(self) -> None:
        if self.tray and self.settings.close_to_tray:
            self.withdraw()
            if not self.settings.tray_hint_shown:
                self.settings.tray_hint_shown = True
                self._save()
                self.tray.notify("Tidy Folders is still running, next to the clock (you may need "
                                 "to click the ^ arrow). Click the icon to open it, or "
                                 "right-click it to quit.")
            return
        self._quit()

    def _quit(self) -> None:
        self._stop_auto()
        if self.tray:
            self.tray.stop()
        self.destroy()


_instance_mutex = None  # held for the life of the process


def _another_copy_running() -> bool:
    """True if Tidy Folders is already open (two copies would fight over the same files)."""
    import ctypes
    from ctypes import wintypes
    global _instance_mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\TidyFoldersSingleInstance")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def _ask_running_copy_to_show() -> bool:
    """Tell the copy that's already running (maybe hidden in the tray) to show its window."""
    import ctypes
    from ctypes import wintypes
    ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY: let it come to the front
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenEventW(0x0002, False, SHOW_EVENT_NAME)  # EVENT_MODIFY_STATE
    if not handle:
        return False
    kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)
    return True


def main() -> None:
    start_hidden = "--tray" in sys.argv[1:]
    if sys.platform == "win32":
        import ctypes
        if _another_copy_running():
            if not start_hidden and not _ask_running_copy_to_show():
                ctypes.windll.user32.MessageBoxW(None, f"{APP_NAME} is already open.", APP_NAME, 0x40)
            return
        try:  # group under our own icon in the taskbar, not Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TidyFolders.App")
        except Exception:
            pass
        try:  # crisp text on high-resolution screens
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App(start_hidden=start_hidden).mainloop()


if __name__ == "__main__":
    main()
