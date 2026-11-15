"""Tests for the sorting engine. Run with:  python -m unittest discover tests"""
import errno
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tidy_folders import engine  # noqa: E402
from tidy_folders.rules import Settings, load_settings, save_settings  # noqa: E402
from tidy_folders.watcher import AutoSorter  # noqa: E402

OLD = time.time() - 40 * 24 * 3600  # 40 days ago


def make(folder: Path, name: str, content: str = "x", mtime: float = OLD) -> Path:
    p = Path(folder) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    os.utime(p, (mtime, mtime))
    return p


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "Downloads"
        self.root.mkdir()
        self.history = engine.History(self.base / "history.json")
        self.settings = Settings()

    def tearDown(self):
        self.tmp.cleanup()

    def plan_map(self, folder=None, **kw):
        folder = folder or self.root
        return {Path(m.src).name: Path(os.path.relpath(m.dst, folder))
                for m in engine.plan_sort(folder, self.settings, **kw)}

    def test_sort_and_undo_roundtrip(self):
        for f in ["photo.jpg", "report.PDF", "song.mp3", "budget.xlsx", "setup.exe",
                  "weird.xyz", "noext"]:
            make(self.root, f)
        make(self.root, "Projects/keep.jpg")              # inside a subfolder: never touched
        make(self.root, "Images/photo.jpg", "older one")   # destination name already taken
        skipped = ["desktop.ini", "~$draft.docx", "movie.mp4.crdownload", "App.lnk", ".hidden.txt"]
        for f in skipped:
            make(self.root, f)

        self.assertEqual(self.plan_map(), {
            "budget.xlsx": Path("Spreadsheets/budget.xlsx"),
            "noext": Path("Other/noext"),
            "photo.jpg": Path("Images/photo (2).jpg"),
            "report.PDF": Path("Documents/report.PDF"),
            "setup.exe": Path("Installers/setup.exe"),
            "song.mp3": Path("Music/song.mp3"),
            "weird.xyz": Path("Other/weird.xyz"),
        })

        moves = engine.plan_sort(self.root, self.settings)
        run, errors = engine.apply_moves(moves, self.root, history=self.history)
        self.assertEqual(errors, [])
        self.assertEqual(len(run["moves"]), 7)
        for m in moves:
            self.assertFalse(Path(m.src).exists())
            self.assertTrue(Path(m.dst).exists())
        self.assertTrue((self.root / "Projects/keep.jpg").exists())
        self.assertEqual((self.root / "Images/photo.jpg").read_text(), "older one")
        for f in skipped:
            self.assertTrue((self.root / f).exists(), f)
        self.assertEqual(len(self.history.runs()), 1)

        restored, problems = engine.undo_run(self.history.latest_undoable())
        self.assertEqual((restored, problems), (7, []))
        for m in moves:
            self.assertTrue(Path(m.src).exists())
        self.assertEqual((self.root / "Images/photo.jpg").read_text(), "older one")
        self.assertTrue((self.root / "Images").is_dir())   # existed before, kept
        self.assertFalse((self.root / "Music").exists())   # created by the sort, removed
        self.assertFalse((self.root / "Other").exists())

    def test_recent_files_wait(self):
        make(self.root, "new.pdf", mtime=time.time())
        self.assertEqual(self.plan_map(min_age=60), {})
        self.assertEqual(self.plan_map(min_age=0), {"new.pdf": Path("Documents/new.pdf")})

    def test_download_in_progress_is_skipped(self):
        make(self.root, "big.zip")
        make(self.root, "big.zip.part")
        self.assertEqual(self.plan_map(), {})

    def test_unknown_types_can_stay(self):
        make(self.root, "weird.xyz")
        self.settings.other_folder = False
        self.assertEqual(self.plan_map(), {})

    def test_shortcuts_option(self):
        make(self.root, "App.lnk")
        self.assertEqual(self.plan_map(), {})
        self.settings.skip_shortcuts = False
        self.assertEqual(self.plan_map(), {"App.lnk": Path("Other/App.lnk")})

    def test_month_modes(self):
        when = datetime(2025, 3, 15, 12).timestamp()
        make(self.root, "a.jpg", mtime=when)
        self.settings.mode = "type_month"
        self.assertEqual(self.plan_map(), {"a.jpg": Path("Images/2025-03/a.jpg")})
        self.settings.mode = "month"
        self.assertEqual(self.plan_map(), {"a.jpg": Path("2025-03/a.jpg")})

    def test_no_images_inside_images(self):
        images = self.root / "Images"
        make(images, "a.jpg")
        make(images, "notes.txt")
        self.assertEqual(self.plan_map(images), {"notes.txt": Path("Documents/notes.txt")})

    def test_custom_category_and_case(self):
        self.settings.categories = {"Photos": ["JPG", ".png"], **self.settings.categories}
        make(self.root, "a.JPG")
        self.assertEqual(self.plan_map(), {"a.JPG": Path("Photos/a.JPG")})

    def test_unsafe_folders_blocked(self):
        self.assertIsNotNone(engine.folder_problem(Path(self.root.anchor)))
        self.assertIsNotNone(engine.folder_problem(Path.home()))
        if os.environ.get("SystemRoot"):
            self.assertIsNotNone(engine.folder_problem(os.environ["SystemRoot"]))
        if os.environ.get("APPDATA"):
            self.assertIsNotNone(engine.folder_problem(os.environ["APPDATA"]))
        self.assertIsNotNone(engine.folder_problem(self.base / "missing"))
        self.assertIsNone(engine.folder_problem(self.root))

    def test_undo_when_file_was_moved_away(self):
        make(self.root, "a.pdf")
        make(self.root, "b.pdf")
        run, _ = engine.apply_moves(engine.plan_sort(self.root, self.settings), self.root,
                                    history=self.history)
        (self.root / "Documents/a.pdf").unlink()
        restored, problems = engine.undo_run(run)
        self.assertEqual(restored, 1)
        self.assertEqual(len(problems), 1)
        self.assertTrue((self.root / "b.pdf").exists())

    def test_undo_never_overwrites(self):
        make(self.root, "a.pdf", "sorted")
        run, _ = engine.apply_moves(engine.plan_sort(self.root, self.settings), self.root)
        make(self.root, "a.pdf", "new download")
        restored, problems = engine.undo_run(run)
        self.assertEqual(restored, 1)
        self.assertEqual((self.root / "a.pdf").read_text(), "new download")
        self.assertEqual((self.root / "a (2).pdf").read_text(), "sorted")
        self.assertEqual(len(problems), 1)

    def test_batch_undo_spans_folders(self):
        other = self.base / "Desktop"
        make(self.root, "a.pdf")
        make(other, "b.mp3")
        for folder in (self.root, other):
            engine.apply_moves(engine.plan_sort(folder, self.settings), folder,
                               history=self.history, batch="click1")
        self.assertEqual(len(self.history.latest_undoable_batch()), 2)

    def test_category_names_validated(self):
        self.assertIsNone(engine.validate_category_name("Tax Papers"))
        for bad in ["", "a/b", "CON", "name.", "what?"]:
            self.assertIsNotNone(engine.validate_category_name(bad), bad)

    def test_settings_roundtrip_and_corrupt_file(self):
        path = self.base / "settings.json"
        s = Settings(folders=[str(self.root)], mode="month", auto_sort=True)
        save_settings(s, path)
        loaded = load_settings(path)
        self.assertEqual((loaded.folders, loaded.mode, loaded.auto_sort),
                         ([str(self.root)], "month", True))
        path.write_text("{not json")
        self.assertEqual(load_settings(path).folders, [])
        path.write_text('{"mode": "month"}', encoding="utf-8-sig")  # file saved with a BOM
        self.assertEqual(load_settings(path).mode, "month")


class NameRuleTests(unittest.TestCase):
    """Course folders and code words, using a copy of the UoA\\2026\\Sem 2 layout."""

    COURSES = ["ELECTENG 204", "ELECTENG 209", "ELECTENG 292", "ENGGEN 204"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.downloads = self.base / "Downloads"
        self.downloads.mkdir()
        self.sem = self.base / "UoA" / "2026" / "Sem 2"
        for course in self.COURSES:
            (self.sem / course).mkdir(parents=True)
        (self.base / "UoA" / "Competitions").mkdir()
        self.settings = Settings(course_roots=[str(self.sem)])

    def tearDown(self):
        self.tmp.cleanup()

    def where(self, folder=None):
        folder = folder or self.downloads
        return {Path(m.src).name: Path(m.dst).parent.relative_to(self.base)
                for m in engine.plan_sort(folder, self.settings)}

    def test_course_codes_match_loosely(self):
        for name in ["ELECTENG292_Assignment1.pdf", "electeng 292 lab notes.docx",
                     "ENGGEN-204 tutorial.pptx", "ElectEng_204.zip", "Lab3 (ELECTENG209).pdf",
                     "ELECTENG2920.pdf", "XELECTENG292.pdf", "holiday.jpg", "2026 report.pdf"]:
            make(self.downloads, name)
        sem = Path("UoA/2026/Sem 2")
        self.assertEqual(self.where(), {
            "ELECTENG292_Assignment1.pdf": sem / "ELECTENG 292",
            "electeng 292 lab notes.docx": sem / "ELECTENG 292",
            "ENGGEN-204 tutorial.pptx": sem / "ENGGEN 204",
            "ElectEng_204.zip": sem / "ELECTENG 204",
            "Lab3 (ELECTENG209).pdf": sem / "ELECTENG 209",
            "ELECTENG2920.pdf": Path("Downloads/Documents"),   # different number
            "XELECTENG292.pdf": Path("Downloads/Documents"),   # part of another word
            "holiday.jpg": Path("Downloads/Images"),
            "2026 report.pdf": Path("Downloads/Documents"),
        })

    def test_only_code_like_folder_names_count(self):
        self.settings.course_roots = [str(self.base / "UoA")]  # holds "2026" and "Competitions"
        make(self.downloads, "2026 Competitions entry.pdf")
        self.assertEqual(self.where(), {"2026 Competitions entry.pdf": Path("Downloads/Documents")})
        self.assertEqual(engine.course_folders(self.sem), [self.sem / c for c in self.COURSES])

    def test_code_words_and_order(self):
        finance = self.base / "Finance"
        self.settings.keyword_rules = [{"word": "invoice", "folder": str(finance)}]
        make(self.downloads, "march_invoice.pdf")
        make(self.downloads, "Invoices 2026.xlsx")
        make(self.downloads, "ELECTENG292 invoice.pdf")   # course folders are checked first
        self.assertEqual(self.where(), {
            "march_invoice.pdf": Path("Finance"),
            "Invoices 2026.xlsx": Path("Finance"),
            "ELECTENG292 invoice.pdf": Path("UoA/2026/Sem 2/ELECTENG 292"),
        })

    def test_move_and_undo(self):
        finance = self.base / "Finance"  # doesn't exist yet: created, then removed by undo
        self.settings.keyword_rules = [{"word": "invoice", "folder": str(finance)}]
        make(self.downloads, "ELECTENG292_Lab1.pdf", "lab")
        make(self.downloads, "invoice.pdf", "money")
        run, errors = engine.apply_moves(engine.plan_sort(self.downloads, self.settings), self.downloads)
        self.assertEqual(errors, [])
        self.assertEqual((self.sem / "ELECTENG 292" / "ELECTENG292_Lab1.pdf").read_text(), "lab")
        self.assertEqual((finance / "invoice.pdf").read_text(), "money")
        self.assertEqual({m["rule"] for m in run["moves"]}, {"course", "word"})
        restored, problems = engine.undo_run(run)
        self.assertEqual((restored, problems), (2, []))
        self.assertTrue((self.downloads / "ELECTENG292_Lab1.pdf").exists())
        self.assertFalse(finance.exists())
        self.assertTrue((self.sem / "ELECTENG 292").is_dir())  # existed before: kept

    def test_never_overwrites_in_course_folder(self):
        make(self.sem / "ELECTENG 292", "ELECTENG292_Lab1.pdf", "old")
        make(self.downloads, "ELECTENG292_Lab1.pdf", "new")
        self.assertEqual(self.where(), {"ELECTENG292_Lab1.pdf": Path("UoA/2026/Sem 2/ELECTENG 292")})
        engine.apply_moves(engine.plan_sort(self.downloads, self.settings), self.downloads)
        self.assertEqual((self.sem / "ELECTENG 292" / "ELECTENG292_Lab1.pdf").read_text(), "old")
        self.assertEqual((self.sem / "ELECTENG 292" / "ELECTENG292_Lab1 (2).pdf").read_text(), "new")

    def test_files_already_in_their_course_folder_stay(self):
        course = self.sem / "ELECTENG 292"
        make(course, "ELECTENG292_Lab1.pdf")
        self.assertEqual(self.where(course), {})

    def test_unsafe_rule_folder_is_ignored(self):
        if not os.environ.get("SystemRoot"):
            self.skipTest("Windows only")
        self.settings.keyword_rules = [{"word": "driver", "folder": os.environ["SystemRoot"]}]
        make(self.downloads, "driver.pdf")
        self.assertEqual(self.where(), {})

    def test_moves_between_drives(self):
        make(self.downloads, "ELECTENG292_Lab1.pdf", "lab")
        real_rename = engine.os.rename

        def cross_drive(src, dst):
            raise OSError(errno.EXDEV, "cross-device link")
        engine.os.rename = cross_drive
        try:
            run, errors = engine.apply_moves(engine.plan_sort(self.downloads, self.settings), self.downloads)
            self.assertEqual(errors, [])
            self.assertFalse((self.downloads / "ELECTENG292_Lab1.pdf").exists())
            self.assertEqual((self.sem / "ELECTENG 292" / "ELECTENG292_Lab1.pdf").read_text(), "lab")
            self.assertEqual(engine.undo_run(run), (1, []))
            self.assertTrue((self.downloads / "ELECTENG292_Lab1.pdf").exists())
        finally:
            engine.os.rename = real_rename

    def test_settings_keep_rules(self):
        path = self.base / "settings.json"
        s = Settings(course_roots=[str(self.sem)],
                     keyword_rules=[{"word": "invoice", "folder": "C:\\Finance"}, {"bad": 1}])
        save_settings(s, path)
        loaded = load_settings(path)
        self.assertEqual(loaded.course_roots, [str(self.sem)])
        self.assertEqual(loaded.keyword_rules, [{"word": "invoice", "folder": "C:\\Finance"}])


class AutoSorterTests(unittest.TestCase):
    def test_sorts_old_files_and_waits_for_new_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Downloads"
            make(root, "old.pdf")
            make(root, "fresh.pdf", mtime=time.time())
            settings = Settings(folders=[str(root)], settle_seconds=60, interval_seconds=5)
            history = engine.History(Path(tmp) / "history.json")
            got = threading.Event()
            sorter = AutoSorter(settings, history, lambda run, errs: got.set())
            sorter.start()
            try:
                self.assertTrue(got.wait(10), "auto-sort never ran")
            finally:
                sorter.stop()
            self.assertTrue((root / "Documents/old.pdf").exists())
            self.assertTrue((root / "fresh.pdf").exists())
            self.assertEqual(history.runs()[0]["source"], "auto")


if __name__ == "__main__":
    unittest.main()
