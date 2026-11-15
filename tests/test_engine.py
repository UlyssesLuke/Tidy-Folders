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
    """Course folders and code words, on a made-up Uni folder with years and semesters."""

    COURSES = {  # where each course folder lives, inside "Uni"
        "2025/Semester 2/MATHS 108": "older copy of a retaken course",
        "2026/Semester 1/ELECTENG 101": "",
        "2026/Semester 1/COMPSCI 101 - Intro": "",
        "2026/Semester 1/MATHS 108": "the newest MATHS 108",
        "2026/Semester 2/ELECTENG 102": "",
        "2026/Semester 2/PHYSICS 160": "",
        "2027/Semester 1/ELECTENG 201": "",
    }

    def setUp(self):
        engine.clear_course_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.downloads = self.base / "Downloads"
        self.downloads.mkdir()
        self.uni = self.base / "Uni"
        for course in self.COURSES:
            (self.uni / course).mkdir(parents=True)
        for not_a_course in ["Clubs", "2026/Semester 2/Assignment 3", "2026/Semester 1/ELECTENG 101/Lab 1",
                             "2026/Semester 1/ELECTENG 101/ELECTENG 102 notes"]:
            (self.uni / not_a_course).mkdir(parents=True)
        self.course = self.uni / "2026" / "Semester 1" / "ELECTENG 101"
        self.settings = Settings(course_roots=[str(self.uni)])

    def tearDown(self):
        self.tmp.cleanup()

    def where(self, folder=None):
        folder = folder or self.downloads
        return {Path(m.src).name: Path(m.dst).parent.relative_to(self.base)
                for m in engine.plan_sort(folder, self.settings)}

    def test_course_folder_names(self):
        self.assertEqual(engine.course_code("ELECTENG 101"), "ELECTENG101")
        self.assertEqual(engine.course_code("ELECTENG 101 - Circuits"), "ELECTENG101")
        self.assertEqual(engine.course_code("maths108g"), "MATHS108G")
        for name in ["2026", "Sem 2", "Semester 2", "Assignment 3", "Notes", "Lab 1", "Clubs", "ELECTENG"]:
            self.assertIsNone(engine.course_code(name), name)

    def test_finds_courses_at_any_depth_but_not_inside_courses(self):
        found = {p.relative_to(self.uni).as_posix() for p in engine.course_folders(self.uni)}
        self.assertEqual(found, set(self.COURSES))   # not Clubs, Assignment 3, Lab 1 or "...notes" inside a course

    def test_course_codes_match_loosely(self):
        for name in ["ELECTENG101_Assignment1.pdf", "electeng 101 lab notes.docx", "COMPSCI-101 tutorial.pptx",
                     "Physics_160 practice test.pdf", "Lab3 (ELECTENG201).pdf", "ELECTENG1010.pdf",
                     "XELECTENG101.pdf", "holiday.jpg", "2026 report.pdf", "Semester 2 timetable.pdf"]:
            make(self.downloads, name)
        s1, s2 = Path("Uni/2026/Semester 1"), Path("Uni/2026/Semester 2")
        self.assertEqual(self.where(), {
            "ELECTENG101_Assignment1.pdf": s1 / "ELECTENG 101",
            "electeng 101 lab notes.docx": s1 / "ELECTENG 101",
            "COMPSCI-101 tutorial.pptx": s1 / "COMPSCI 101 - Intro",
            "Physics_160 practice test.pdf": s2 / "PHYSICS 160",
            "Lab3 (ELECTENG201).pdf": Path("Uni/2027/Semester 1/ELECTENG 201"),
            "ELECTENG1010.pdf": Path("Downloads/Documents"),    # different number
            "XELECTENG101.pdf": Path("Downloads/Documents"),    # part of another word
            "holiday.jpg": Path("Downloads/Images"),
            "2026 report.pdf": Path("Downloads/Documents"),
            "Semester 2 timetable.pdf": Path("Downloads/Documents"),
        })

    def test_newest_copy_of_a_course_wins(self):
        make(self.downloads, "MATHS108 quiz.pdf")
        self.assertEqual(self.where(), {"MATHS108 quiz.pdf": Path("Uni/2026/Semester 1/MATHS 108")})

    def test_new_course_folder_is_picked_up(self):
        make(self.downloads, "ENGGEN115 report.pdf")
        self.assertEqual(self.where(), {"ENGGEN115 report.pdf": Path("Downloads/Documents")})
        (self.uni / "2026" / "Semester 2" / "ENGGEN 115").mkdir()
        engine.clear_course_cache()  # the app does this itself after 15 seconds, or when rules change
        self.assertEqual(self.where(), {"ENGGEN115 report.pdf": Path("Uni/2026/Semester 2/ENGGEN 115")})

    def test_code_words_and_order(self):
        finance = self.base / "Finance"
        self.settings.keyword_rules = [{"word": "invoice", "folder": str(finance)}]
        make(self.downloads, "march_invoice.pdf")
        make(self.downloads, "Invoices 2026.xlsx")
        make(self.downloads, "ELECTENG101 invoice.pdf")   # course folders are checked first
        self.assertEqual(self.where(), {
            "march_invoice.pdf": Path("Finance"),
            "Invoices 2026.xlsx": Path("Finance"),
            "ELECTENG101 invoice.pdf": Path("Uni/2026/Semester 1/ELECTENG 101"),
        })

    def test_move_and_undo(self):
        finance = self.base / "Finance"  # doesn't exist yet: created, then removed by undo
        self.settings.keyword_rules = [{"word": "invoice", "folder": str(finance)}]
        make(self.downloads, "ELECTENG101_Lab1.pdf", "lab")
        make(self.downloads, "invoice.pdf", "money")
        run, errors = engine.apply_moves(engine.plan_sort(self.downloads, self.settings), self.downloads)
        self.assertEqual(errors, [])
        self.assertEqual((self.course / "ELECTENG101_Lab1.pdf").read_text(), "lab")
        self.assertEqual((finance / "invoice.pdf").read_text(), "money")
        self.assertEqual({m["rule"] for m in run["moves"]}, {"course", "word"})
        restored, problems = engine.undo_run(run)
        self.assertEqual((restored, problems), (2, []))
        self.assertTrue((self.downloads / "ELECTENG101_Lab1.pdf").exists())
        self.assertFalse(finance.exists())
        self.assertTrue(self.course.is_dir())  # existed before: kept

    def test_never_overwrites_in_course_folder(self):
        make(self.course, "ELECTENG101_Lab1.pdf", "old")
        make(self.downloads, "ELECTENG101_Lab1.pdf", "new")
        engine.apply_moves(engine.plan_sort(self.downloads, self.settings), self.downloads)
        self.assertEqual((self.course / "ELECTENG101_Lab1.pdf").read_text(), "old")
        self.assertEqual((self.course / "ELECTENG101_Lab1 (2).pdf").read_text(), "new")

    def test_files_already_in_their_course_folder_stay(self):
        make(self.course, "ELECTENG101_Lab1.pdf")
        self.assertEqual(self.where(self.course), {})

    def test_unsafe_rule_folder_is_ignored(self):
        if not os.environ.get("SystemRoot"):
            self.skipTest("Windows only")
        self.settings.keyword_rules = [{"word": "driver", "folder": os.environ["SystemRoot"]}]
        make(self.downloads, "driver.pdf")
        self.assertEqual(self.where(), {})

    def test_moves_between_drives(self):
        make(self.downloads, "ELECTENG101_Lab1.pdf", "lab")
        real_rename = engine.os.rename

        def cross_drive(src, dst):
            raise OSError(errno.EXDEV, "cross-device link")
        engine.os.rename = cross_drive
        try:
            run, errors = engine.apply_moves(engine.plan_sort(self.downloads, self.settings), self.downloads)
            self.assertEqual(errors, [])
            self.assertFalse((self.downloads / "ELECTENG101_Lab1.pdf").exists())
            self.assertEqual((self.course / "ELECTENG101_Lab1.pdf").read_text(), "lab")
            self.assertEqual(engine.undo_run(run), (1, []))
            self.assertTrue((self.downloads / "ELECTENG101_Lab1.pdf").exists())
        finally:
            engine.os.rename = real_rename

    def test_settings_keep_rules(self):
        path = self.base / "settings.json"
        s = Settings(course_roots=[str(self.uni)],
                     keyword_rules=[{"word": "invoice", "folder": "C:\\Finance"}, {"bad": 1}])
        save_settings(s, path)
        loaded = load_settings(path)
        self.assertEqual(loaded.course_roots, [str(self.uni)])
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
