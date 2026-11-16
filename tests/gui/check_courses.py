"""The Courses row in the Preview: the dropdown, Exclude / Include all, one course, then a real Tidy up!."""
from helpers import check, find, finish, make, pump, setup, shot, texts, use, wait_idle

work = setup("courses")
uni = work / "Uni"
for c in ["2026/Semester 1/ELECTENG 101", "2026/Semester 1/COMPSCI 101", "2026/Semester 2/MATHS 108"]:
    (uni / c).mkdir(parents=True)
downloads = work / "Downloads"
make(downloads, ["ELECTENG101 Test (2024).pdf", "ELECTENG101 Test (2025).pdf", "ELECTENG101 notes.docx",
                 "compsci101 lab 1.zip", "MATHS108 quiz.pdf", "photo.jpg", "report.docx"])

from tkinter import messagebox  # noqa: E402
from tidy_folders import gui, rules  # noqa: E402

messagebox.askyesno = lambda *a, **k: True
rules.save_settings(rules.Settings(folders=[str(downloads)], course_roots=[str(uni)]))

app = use(gui.App())
app.geometry("1120x900")
pump(1.0)
app._preview()
pump()
shown = texts()
check("one Courses row", "Courses  ·  5 files  ·  3 courses" in shown)
check("courses aren't listed one by one until opened", not any(t.startswith("ELECTENG 101  ·") for t in shown))
shot("courses-closed.png")

find("Show courses ▾").event_generate("<Button-1>")
pump()
shown = texts()
check("the dropdown shows each course", all(any(t.startswith(c + "  ·") for t in shown)
                                            for c in ["ELECTENG 101", "COMPSCI 101", "MATHS 108"]))
check("the toggle now says Hide courses", find("Hide courses ▴") is not None)

app._skip_group("course:ELECTENG101")  # Exclude on one course
pump()
shown = texts()
check("excluding one course", "Courses  ·  2 files  ·  3 courses  ·  1 excluded" in shown
      and "Include all courses" in shown)
check("the dropdown stays open", find("Hide courses ▴") is not None)
shot("courses-one-excluded.png")

app._exclude_all("course")
pump()
shown = texts()
check("all courses excluded", "Courses  ·  5 files  ·  3 courses  ·  excluded" in shown
      and "Exclude all courses" not in shown)
check("each course says it's excluded with all courses", "excluded with all courses" in shown)
check("only the photo and report are left to move", app.counts[str(downloads)] == 2)

app._include_all("course")
pump()
check("Include all brings every course back", rules.load_settings().skipped_groups == []
      and app.counts[str(downloads)] == 7)

app._skip_group("course:COMPSCI101")
pump()
app.tidy_btn.invoke()
wait_idle()
check("Tidy up! sorted the included courses",
      (uni / "2026/Semester 1/ELECTENG 101/ELECTENG101 notes.docx").exists()
      and (uni / "2026/Semester 2/MATHS 108/MATHS108 quiz.pdf").exists())
check("the excluded course's file stayed put", (downloads / "compsci101 lab 1.zip").exists())
finish("COURSES")
