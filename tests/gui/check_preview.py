"""The Preview's details: the new-folder symbol and its note, Show all / Show less, and the
Add file type box on the Categories page."""
import tkinter as tk

from helpers import check, finish, labels, make, pump, setup, shot, texts, use

work = setup("preview")
downloads = work / "Downloads"
(downloads / "Images").mkdir(parents=True)  # Images already exists, Code doesn't
make(downloads, ["Hello_World.c", "photo.jpg", "a1.pdf", "a2.pdf", "a3.pdf", "a4.pdf", "a5.pdf"])

from tidy_folders import gui, rules  # noqa: E402

rules.save_settings(rules.Settings(folders=[str(downloads)]))


def row_of(title_start):
    """The plan row whose title starts with `title_start`."""
    title = next(w for w in labels(app.panel) if str(w.cget("text")).startswith(title_start))
    return title.master.master


def badges(row):
    return [w for w in labels(row) if getattr(w, "image_name", "") == "new_folder"]


app = use(gui.App())
pump(1.0)
app._preview()
pump()
check("Code row shows the new-folder symbol (Downloads\\Code doesn't exist yet)", len(badges(row_of("Code"))) == 1)
check("Images row has none (Downloads\\Images already exists)", not badges(row_of("Images")))

badge = badges(row_of("Code"))[0]
app.attributes("-topmost", True)
pump(0.3)
badge.event_generate("<Enter>")
pump(0.6)
note = " ".join(t for top in badge.winfo_children() if isinstance(top, tk.Toplevel) for t in texts(top))
check("hovering it explains it", "New folder: Tidy Folders will create" in note and str(downloads / "Code") in note)
shot("preview-new-folder-note.png")
badge.event_generate("<Leave>")
pump(0.3)

docs = row_of("Documents")
toggle = next(w for w in labels(docs) if w.cget("text") == "Show all")
names = next(w for w in labels(docs) if "more" in str(w.cget("text")))
short = names.cget("text")
toggle.event_generate("<Button-1>")
pump(0.2)
check("Show all lists every file and becomes Show less",
      names.cget("text").count(".pdf") == 5 and toggle.cget("text") == "Show less")
toggle.event_generate("<Button-1>")
pump(0.2)
check("Show less folds it back up", names.cget("text") == short and toggle.cget("text") == "Show all")

app.show_view("cats")
pump()
check("Add file type is a box in the grid", app.add_type_box.winfo_exists() and
      "Add file type" in texts(app.add_type_box))
app.cat_scroll.canvas.yview_moveto(1.0)
pump()
shot("preview-add-file-type-box.png")
finish("PREVIEW")
