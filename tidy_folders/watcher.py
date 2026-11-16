"""Automatic sorting: a background thread that keeps the chosen folders tidy."""
from __future__ import annotations

import copy
import threading
from typing import Callable

from . import crashlog, engine
from .rules import Settings


class AutoSorter:
    """Checks the folders every `interval_seconds` and sorts anything new.

    Files younger than `settle_seconds` are left alone so downloads and
    saves have time to finish. `on_run(run, new_errors)` is called from the
    background thread after each sort that moved something or hit a new error.
    """

    def __init__(self, settings: Settings, history: engine.History,
                 on_run: Callable[[dict, list[str]], None]):
        self._settings = copy.deepcopy(settings)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._history = history
        self._on_run = on_run
        self._reported: set[str] = set()  # report each problem once, not every pass
        self._thread = threading.Thread(target=self._loop, name="tidy-auto-sort", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def update_settings(self, settings: Settings) -> None:
        with self._lock:
            self._settings = copy.deepcopy(settings)
        self._wake.set()  # re-check now with the new settings

    def _snapshot(self) -> Settings:
        with self._lock:
            return copy.deepcopy(self._settings)

    def sort_once(self) -> int:
        settings = self._snapshot()
        moved = 0
        for folder in settings.folders:
            if self._stop.is_set():
                break
            if engine.folder_problem(folder):
                continue
            moves = engine.plan_sort(folder, settings, min_age=settings.settle_seconds)
            if not moves:
                continue
            run, errors = engine.apply_moves(moves, folder, "auto", self._history)
            new_errors = [e for e in errors if e not in self._reported]
            self._reported.update(new_errors)
            if run["moves"] or new_errors:
                self._on_run(run, new_errors)
            moved += len(run["moves"])
        return moved

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sort_once()
            except Exception as e:  # keep the thread alive no matter what (details go to error.log)
                crashlog.write(type(e), e, e.__traceback__, "auto-sort")
                self._on_run({"folder": "", "moves": []}, [f"Auto-sort hit a problem: {e}"])
            self._wake.wait(self._snapshot().interval_seconds)
            self._wake.clear()
