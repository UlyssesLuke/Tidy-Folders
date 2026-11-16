"""Take the screenshots used in README.md (saved to docs/screenshots), from made-up sample folders.

    python packaging\\readme_screenshots.py

Windows open and close by themselves: leave the mouse alone for a few seconds. Uses temporary
folders and settings, never your real ones. Folder paths are shown as C:\\Users\\you\\... .
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "gui"))

from helpers import make, pump, setup, shot, use  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
work = setup("readme")
home = work / "you"
downloads, desktop = home / "Downloads", home / "Desktop"
uni = home / "Documents" / "Uni" / "2026"
for course in ["Semester 1/ELECTENG 101", "Semester 1/MATHS 108", "Semester 2/COMPSCI 110"]:
    (uni / course).mkdir(parents=True)
make(downloads, ["holiday-beach.jpg", "IMG_2041.PNG", "screenshot-03.png", "tax-return-2025.pdf",
                 "resume.docx", "notes.txt", "ChromeSetup.exe", "project-files.zip", "podcast-ep12.mp3",
                 "birthday.mp4", "budget.xlsx", "slides.pptx", "phone-stand.stl", "bracket.3mf",
                 "ELECTENG101 Lab 1.pdf", "ELECTENG101 notes.docx", "MATHS108 quiz.pdf",
                 "invoice-march.pdf", "invoice-april.pdf"])
make(desktop, ["meme.png", "todo.txt", "song.m4a", "cable-clip.stl"])

from tidy_folders import gui, rules  # noqa: E402

_fit = gui.App._fit_on_resize  # show paths as C:\Users\you\... instead of the temporary folder
gui.App._fit_on_resize = staticmethod(
    lambda label, text, font, side="end": _fit(label, text.replace(str(home), r"C:\Users\you"), font, side))

settings = rules.Settings(folders=[str(downloads), str(desktop)], course_roots=[str(uni.parent)],
                          keyword_rules=[{"word": "invoice", "folder": str(home / "Documents" / "Finance")}])
settings.categories["3D Printing"] = ["stl", "3mf", "gcode"]
settings.category_icons["3D Printing"] = {"glyph": 1, "colour": gui.ICON_COLOURS[1]}
rules.save_settings(settings)

app = use(gui.App())
app.geometry(f"{app.px(1120)}x{app.px(790)}")
pump(1.0)
app._preview()
pump(0.8)
shot("preview.png", folder=OUT)

app.show_view("cats")
pump(0.5)
app.cat_scroll.canvas.yview_moveto(1.0)
pump(0.5)
shot("categories.png", folder=OUT)

dlg = app._edit_category("3D Printing", wait=False)
pump(0.5)
dlg.place.label.configure(text=dlg.place.label.cget("text").replace(str(home), r"C:\Users\you"))
shot("file-type.png", dlg, folder=OUT)
dlg.destroy()
app._quit()
print("saved to", OUT)
