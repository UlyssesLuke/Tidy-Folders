"""Adding course folders and code words, planning with them, Tidy up!, Undo, and removing them."""
from pathlib import Path

from helpers import check, finish, make, pump, setup, shot, use, wait_idle

work = setup("name-rules")
downloads = work / "Downloads"
sem = work / "Uni" / "2026" / "Sem 2"
old_sem = work / "Uni" / "2025" / "Sem 2"
for c in ["ELECTENG 204", "ELECTENG 209", "ELECTENG 292", "ENGGEN 204"]:
    (sem / c).mkdir(parents=True)
for c in ["CHEMMAT 121", "ELECTENG 101", "ENGGEN 115", "ENGGEN 131"]:
    (old_sem / c).mkdir(parents=True)
(work / "Finance").mkdir()
names = ["ELECTENG292_Assignment1.pdf", "electeng 292 lab notes.docx", "ELECTENG292-Lab3.zip",
         "ENGGEN-204 tutorial.pptx", "ElectEng_204 practice test.pdf", "Lab2 (ELECTENG209).pdf",
         "march_invoice.pdf", "holiday.jpg", "resume.docx", "song.mp3"]
make(downloads, names)

from tkinter import filedialog, messagebox  # noqa: E402
from tidy_folders import gui, rules, tray  # noqa: E402

messagebox.askyesno = lambda *a, **k: True
tray.TrayIcon.notify = lambda self, msg, title=None: None
rules.save_settings(rules.Settings(folders=[str(downloads)], course_roots=[str(sem)]))

app = use(gui.App())
pump(1.0)
check("code words need at least 3 letters", app._validate_keyword_rule("ab", str(work / "Finance")))
check("a code word can't send files to the folder being tidied", app._validate_keyword_rule("invoice", str(downloads)))
check("invoice -> Finance is fine", app._validate_keyword_rule("invoice", str(work / "Finance")) is None)
app.settings.keyword_rules.append({"word": "invoice", "folder": str(work / "Finance")})
app._categories_changed()

filedialog.askdirectory = lambda **k: str(old_sem)  # "+ Add course folder" picks the 2025 semester
app._add_course_root()
check("a second course folder was added", app.settings.course_roots == [str(sem), str(old_sem)])
app.show_view("cats")
pump()
shot("name-rules-categories.png")

app._preview()
pump()
plan = {Path(m.src).name: m for moves in app.plans.values() for m in moves}
check("course files are planned into their course folders",
      Path(plan["electeng 292 lab notes.docx"].dst).parent == sem / "ELECTENG 292"
      and Path(plan["ENGGEN-204 tutorial.pptx"].dst).parent == sem / "ENGGEN 204"
      and Path(plan["Lab2 (ELECTENG209).pdf"].dst).parent == sem / "ELECTENG 209")
check("the code word file is planned into Finance", Path(plan["march_invoice.pdf"].dst).parent == work / "Finance")
check("other files are still sorted by type", Path(plan["holiday.jpg"].dst).parent == downloads / "Images")

app.tidy_btn.invoke()
wait_idle()
check("files moved into their folders", (sem / "ELECTENG 292" / "ELECTENG292_Assignment1.pdf").exists()
      and (work / "Finance" / "march_invoice.pdf").exists() and (downloads / "Images" / "holiday.jpg").exists())
check("nothing left loose", app.counts == {str(downloads): 0})
app._undo_last()
wait_idle()
check("Undo brought them all back", all((downloads / n).exists() for n in names))

app._remove_course_root(str(old_sem))
app._remove_keyword_rule(0)
check("course folder and code word removed", app.settings.course_roots == [str(sem)]
      and app.settings.keyword_rules == [])
finish("NAME RULES")
