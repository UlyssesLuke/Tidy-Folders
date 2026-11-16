"""The Code words row in the Preview: its icon, dropdown, new-folder symbol, Exclude / Include all,
one code word, then a real Tidy up!."""
from helpers import check, find, finish, labels, make, pump, setup, shot, texts, use, wait_idle

work = setup("code-words")
uni = work / "Uni"
(uni / "2026/Semester 2/ELECTENG 292").mkdir(parents=True)
finance = work / "Finance"
finance.mkdir()
bombo = work / "Projects" / "BOMBO"  # doesn't exist yet: Tidy up! makes it
downloads = work / "Downloads"
make(downloads, ["march invoice.pdf", "invoice 2.pdf", "BOMBO.txt", "bombo sketch.png", "ELECTENG292 lab.pdf",
                 "photo.jpg", "report.docx"])

from tkinter import messagebox  # noqa: E402
from tidy_folders import gui, rules  # noqa: E402

messagebox.askyesno = lambda *a, **k: True
rules.save_settings(rules.Settings(folders=[str(downloads)], course_roots=[str(uni)],
                                   keyword_rules=[{"word": "invoice", "folder": str(finance)},
                                                  {"word": "BOMBO", "folder": str(bombo)}]))


def row(title):
    return find(title).master.master


def has_badge(title):
    return any(getattr(w, "image_name", "") == "new_folder" for w in labels(row(title)))


app = use(gui.App())
app.geometry("1120x900")
pump(1.0)
app._preview()
pump()
shown = texts()
check("one Code words row", "Code words  ·  4 files  ·  2 code words" in shown)
check("code words aren't listed one by one until opened",
      not any(t.startswith(("BOMBO  ·", "invoice  ·")) for t in shown))
icon = next(w for w in labels(row("Code words  ·  4 files  ·  2 code words")) if str(w.cget("image")))
check("the row uses the Code word icon", str(icon.cget("image")) == str(app.category_sprite("Code word")))
check("the Courses row is still there", "Courses  ·  1 file  ·  1 course" in shown)
check("new-folder symbol on the row (Projects\\BOMBO doesn't exist yet)",
      has_badge("Code words  ·  4 files  ·  2 code words"))
check("the label counts the folders", "→ 2 folders" in shown)
shot("code-words-closed.png")

find("Show code words ▾").event_generate("<Button-1>")
pump()
shown = texts()
check("the dropdown shows each code word", any(t.startswith("BOMBO  ·  2 files") for t in shown)
      and any(t.startswith("invoice  ·  2 files") for t in shown))
child_icon = next(w for w in labels(row("BOMBO  ·  2 files"))
                  if str(w.cget("image")) and getattr(w, "image_name", "") != "new_folder")
check("each code word inside uses the plain folder logo",
      str(child_icon.cget("image")) == str(app.category_sprite("", 1.5)))
check("new-folder symbol only where the folder is new (BOMBO yes, Finance no)",
      has_badge("BOMBO  ·  2 files") and not has_badge("invoice  ·  2 files"))
shot("code-words-open.png")

app._skip_group("word:bombo")
pump()
shown = texts()
check("excluding one code word", "Code words  ·  2 files  ·  2 code words  ·  1 excluded" in shown
      and "Include all code words" in shown)

app._exclude_all("word")
pump()
shown = texts()
check("all code words excluded", "Code words  ·  4 files  ·  2 code words  ·  excluded" in shown
      and "excluded with all code words" in shown)
check("courses are unaffected", "Courses  ·  1 file  ·  1 course" in shown)
app.show_view("cats")
pump()
check("the Categories page lists 'All code words' as excluded",
      any(t.startswith("All code words") for t in texts(app.views["cats"])))
app.show_view("sort")
pump()

app._include_all("word")
pump()
check("Include all brings every code word back", rules.load_settings().skipped_groups == []
      and app.counts[str(downloads)] == 7)

app._skip_group("word:invoice")
pump()
app.tidy_btn.invoke()
wait_idle()
check("Tidy up! made the BOMBO folder and sorted into it",
      (bombo / "BOMBO.txt").exists() and (bombo / "bombo sketch.png").exists())
check("the excluded code word's files stayed put", (downloads / "march invoice.pdf").exists())
check("the course file was still sorted", (uni / "2026/Semester 2/ELECTENG 292/ELECTENG292 lab.pdf").exists())
finish("CODE WORDS")
