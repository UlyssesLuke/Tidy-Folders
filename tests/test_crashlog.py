"""Tests for error.log. Run with:  python -m unittest discover tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tidy_folders import __version__, crashlog  # noqa: E402


class CrashLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("TIDY_FOLDERS_HOME")
        os.environ["TIDY_FOLDERS_HOME"] = self.tmp.name

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("TIDY_FOLDERS_HOME", None)
        else:
            os.environ["TIDY_FOLDERS_HOME"] = self.old_home
        self.tmp.cleanup()

    def boom(self):
        try:
            raise RuntimeError("something broke")
        except RuntimeError as e:
            return type(e), e, e.__traceback__

    def test_error_is_written_with_details(self):
        path = crashlog.write(*self.boom(), "testing")
        self.assertEqual(path, Path(self.tmp.name) / "error.log")
        text = path.read_text(encoding="utf-8")
        self.assertIn("RuntimeError: something broke", text)
        self.assertIn(__version__, text)
        self.assertIn("(testing)", text)
        self.assertIn(str(path), crashlog.message(path))

    def test_log_stays_small(self):
        path = crashlog.log_path()
        path.write_bytes(b"x" * (crashlog.MAX_BYTES + 10))
        crashlog.write(*self.boom())
        size = path.stat().st_size
        self.assertLess(size, crashlog.MAX_BYTES)
        self.assertIn("something broke", path.read_text(encoding="utf-8"))  # the newest error is kept

    def test_message_without_a_log(self):
        self.assertEqual(crashlog.message(None), "Sorry, something went wrong.")


if __name__ == "__main__":
    unittest.main()
