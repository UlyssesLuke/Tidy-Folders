"""Exclude groups in the Preview, Tidy up!, then Include one again from the Categories page."""
from helpers import check, finish, make, pump, setup, shot, use, wait_idle

work = setup("exclude")
uni = work / "Uni"
for c in ["2026/Semester 1/ELECTENG 101", "2026/Semester 2/MATHS 108"]:
    (uni / c).mkdir(parents=True)
downloads = work / "Downloads"
make(downloads, ["ELECTENG101 Test (2024).pdf", "ELECTENG101 Test (2025).pdf", "maths108 quiz.pdf",
                 "mystery.xyz", "weird.abc", "photo.jpg"])

from tkinter import messagebox  # noqa: E402
from tidy_folders import gui, rules  # noqa: E402

messagebox.askyesno = lambda *a, **k: True
rules.save_settings(rules.Settings(folders=[str(downloads)], course_roots=[str(uni)]))

app = use(gui.App())
pump(1.0)
app._preview()
pump()
check("6 files to sort", app.counts[str(downloads)] == 6)

app._skip_group("course:ELECTENG101")
app._skip_group("type:Other")
pump()
check("still previewing, with excluded rows shown", app.phase == "preview"
      and sum(len(m) for m in app.plans.values()) == 6)
check("the folder card counts only what will move", app.counts[str(downloads)] == 2)
check("remembered in settings", rules.load_settings().skipped_groups == ["course:ELECTENG101", "type:Other"])
shot("exclude-preview.png")

app.tidy_btn.invoke()
wait_idle()
check("excluded files stayed in Downloads", all((downloads / n).exists() for n in
      ["ELECTENG101 Test (2024).pdf", "ELECTENG101 Test (2025).pdf", "mystery.xyz", "weird.abc"]))
check("the rest were sorted", (uni / "2026/Semester 2/MATHS 108/maths108 quiz.pdf").exists()
      and (downloads / "Images/photo.jpg").exists())
pump(3.9)
check("the buddy is happy: excluded files don't count as mess", app.counts[str(downloads)] == 0)

app.show_view("cats")
shot("exclude-categories.png")
app._include_group("type:Other")
check("Other included again", rules.load_settings().skipped_groups == ["course:ELECTENG101"]
      and app.counts[str(downloads)] == 2)
finish("EXCLUDE")
