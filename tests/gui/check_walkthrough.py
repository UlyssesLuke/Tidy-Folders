"""The main path through the app: start, Preview, Tidy up!, Categories, History, Undo,
automatic sorting (which starts as soon as it's switched on), and the empty state."""
import os
import time

from helpers import check, finish, make, pump, setup, shot, use, wait_idle

work = setup("walkthrough")
downloads, desktop = work / "Downloads", work / "Desktop"
make(downloads, ["holiday-beach.jpg", "IMG_2041.PNG", "screenshot-03.png", "cat.gif", "logo.svg",
                 "tax-return-2025.pdf", "resume.docx", "notes.txt", "ChromeSetup.exe", "python-3.12.msi",
                 "project-files.zip", "assets.7z", "podcast-ep12.mp3", "birthday.mp4", "budget.xlsx",
                 "slides.pptx", "mystery.xyz", "script.py"])
make(desktop, ["meme.png", "todo.txt", "invoice.pdf", "song.m4a", "font.ttf", "model.stl"])
(downloads / "My Projects").mkdir()

from tkinter import messagebox  # noqa: E402
from tidy_folders import gui, rules, tray  # noqa: E402

messagebox.askyesno = lambda *a, **k: True
tray.TrayIcon.notify = lambda self, msg, title=None: None
rules.save_settings(rules.Settings(folders=[str(downloads), str(desktop)]))

app = use(gui.App())
pump(1.0)
check("counts loose files per folder", app.counts == {str(downloads): 18, str(desktop): 6})
check("the buddy is overwhelmed (24 loose files)", app.mascot.image_name == "faces/dead.png")
check("Downloads card says 18 loose files", app.card_widgets[str(downloads)][1].cget("text") == "18 loose files")
shot("walkthrough-1-start.png")
app._mascot(hover=True)
check("hovering the buddy shows the surprised face", app.mascot.image_name == "faces/surprised.png")
app._mascot(hover=False)

app._preview()
pump()
check("Preview shows the plan", app.phase == "preview" and sum(len(m) for m in app.plans.values()) == 24)
shot("walkthrough-2-preview.png")

app.tidy_btn.invoke()
wait_idle()
check("Tidy up! moved all 24 files", (downloads / "Images" / "holiday-beach.jpg").exists()
      and (desktop / "Fonts" / "font.ttf").exists() and app.result == (24, []))
check("subfolders are never touched", (downloads / "My Projects").is_dir())
check("the buddy celebrates with the tongue face", app.mascot.image_name == "faces/happy_tongue.png")
shot("walkthrough-3-done.png")
pump(3.9)
app.mascot_hover = False  # the real mouse pointer may be resting on the buddy
app._update_mood()
check("then settles on happy", app.mascot.image_name == "faces/happy.png")

app.show_view("cats")
shot("walkthrough-4-categories.png")
app.show_view("hist")
shot("walkthrough-5-history.png")

app._undo_last()
wait_idle()
check("Undo put everything back", (downloads / "holiday-beach.jpg").exists() and app.counts[str(downloads)] == 18)

app.show_view("sort")
app.settings.interval_seconds = 5
app._flip_auto()  # no Tidy up! click: switching it on is enough
check("switching auto-sort on starts it straight away", app.settings.auto_sort and app.auto is not None)
end = time.time() + 12
while time.time() < end and not (downloads / "Images" / "holiday-beach.jpg").exists():
    pump(0.3)
pump(1.0)
check("it tidied the loose files by itself", (downloads / "Images" / "holiday-beach.jpg").exists()
      and (desktop / "Fonts" / "font.ttf").exists() and not (downloads / "resume.docx").exists())
make(downloads, ["new-download.pdf"])
end = time.time() + 12
while time.time() < end and (downloads / "new-download.pdf").exists():
    pump(0.3)
check("after that, new files are tidied by themselves", (downloads / "Documents" / "new-download.pdf").exists())
end = time.time() + 5
while time.time() < end and (app.animating or app.busy):
    pump(0.2)
app.mascot_hover = False
app._update_mood()
check("the buddy is smug while auto-sort is on", app.mascot.image_name == "faces/smug.png")
app._flip_auto()
pump(0.5)
check("auto-sort off again", app.auto is None)

app.settings.folders = []
app._save()
app._remove_folder("nothing")  # refresh with no folders
pump()
check("empty state with no folders", app.mascot.image_name == "faces/front.png")
shot("walkthrough-6-empty.png")
finish("WALKTHROUGH")
