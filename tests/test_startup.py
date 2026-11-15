"""Tests for start-with-Windows. Uses a throwaway registry key, never the real start-up list."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tidy_folders import startup  # noqa: E402

TEST_PARENT = r"Software\TidyFoldersTest"
TEST_KEY = TEST_PARENT + r"\Run"


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class StartupTests(unittest.TestCase):
    def setUp(self):
        self.saved = (startup.RUN_KEY, startup.supported, startup.command)
        startup.RUN_KEY = TEST_KEY

    def tearDown(self):
        startup.RUN_KEY, startup.supported, startup.command = self.saved
        import winreg
        for key in (TEST_KEY, TEST_PARENT):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except OSError:
                pass

    def test_turn_on_and_off(self):
        self.assertFalse(startup.is_enabled())
        startup.enable('"C:\\Apps\\Tidy Folders.exe" --tray')
        self.assertTrue(startup.is_enabled())
        self.assertEqual(startup.current_command(), '"C:\\Apps\\Tidy Folders.exe" --tray')
        startup.disable()
        self.assertFalse(startup.is_enabled())
        startup.disable()  # turning it off twice is fine

    def test_follows_the_exe_when_it_moves(self):
        startup.supported = lambda: True
        startup.enable('"C:\\Old place\\Tidy Folders.exe" --tray')
        startup.command = lambda: '"C:\\New place\\Tidy Folders.exe" --tray'
        startup.refresh_path()
        self.assertEqual(startup.current_command(), '"C:\\New place\\Tidy Folders.exe" --tray')

    def test_refresh_does_nothing_when_off(self):
        startup.supported = lambda: True
        startup.refresh_path()
        self.assertFalse(startup.is_enabled())

    def test_source_checkout_cannot_register(self):
        self.assertFalse(getattr(sys, "frozen", False))
        self.assertFalse(self.saved[1]())  # the real supported(): False when not an .exe


if __name__ == "__main__":
    unittest.main()
