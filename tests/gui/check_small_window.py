"""The smallest window size: every page should fit without anything sticking out. Plus adding and
editing a file type with the logo picker (including uploading your own picture)."""
from helpers import PROJECT, check, finish, make, pump, setup, shot, use

work = setup("small-window")
uni = work / "Uni"
courses = ["CHEMMAT 121", "COMPSYS 201", "ELECTENG 101", "ELECTENG 102", "ELECTENG 201", "ELECTENG 202",
           "ELECTENG 203", "ENGGEN 115", "ENGGEN 121", "ENGGEN 131", "ENGSCI 111", "MATHS 108", "PHYSICS 160"]
for i, c in enumerate(courses):
    (uni / f"202{5 + i % 2}" / f"Semester {1 + i % 2}" / c).mkdir(parents=True)
downloads = work / "Downloads"
make(downloads, ["ELECTENG101 Test 2 (2022) with a really long file name for wrapping.pdf", "ELECTENG101 notes.docx",
                 "ENGGEN115 Team Report Brief and Rubric for the whole semester.pdf", "MATHS108 quiz.pdf",
                 "photo.jpg", "report.docx", "mystery.xyz", "song.mp3", "game_save.sav", "invoice 7.pdf"])

from tkinter import filedialog, messagebox  # noqa: E402
from tidy_folders import gui, rules  # noqa: E402

messagebox.askyesno = lambda *a, **k: True
rules.save_settings(rules.Settings(folders=[str(downloads)], course_roots=[str(uni)],
                                   keyword_rules=[{"word": "invoice", "folder": str(work / "Finance")}],
                                   skipped_groups=["type:Other", "type:Images", "type:Documents", "course:MATHS108"]))


def sticking_out(widget, right_edge):
    """Visible widgets whose right edge goes past `right_edge` (screen x)."""
    bad = []
    for w in widget.winfo_children():
        if w.winfo_ismapped() and w.winfo_rootx() + w.winfo_width() > right_edge + 2 and w.winfo_width() > 4:
            bad.append(f"{w.winfo_class()} '{str(w.cget('text'))[:30] if 'text' in w.keys() else ''}'")
        bad += sticking_out(w, right_edge)
    return bad


app = use(gui.App())
app.geometry(f"{app.px(940)}x{app.px(680)}")
pump(1.0)
app._preview()
app.expanded = {"course": True, "word": True}
app._show_panel()
pump(1.0)
shot("small-window-sort.png")
bad = sticking_out(app.panel, app.panel.winfo_rootx() + app.panel.winfo_width())
check(f"the plan fits ({bad[:3]})", not bad)
bad = sticking_out(app.views["sort"], app.winfo_rootx() + app.winfo_width())
check(f"the Sort page fits ({bad[:3]})", not bad)
bad = sticking_out(app.sidebar, app.sidebar.winfo_rootx() + app.sidebar.winfo_width())
check(f"the sidebar fits ({bad[:3]})", not bad)

app.show_view("cats")
pump(1.0)
shot("small-window-categories.png")
bad = sticking_out(app.views["cats"], app.winfo_rootx() + app.winfo_width())
check(f"the Categories page fits ({bad[:3]})", not bad)
check("file types drop to 2 per row", app._cat_cols == 2)

dlg = app._add_category(wait=False)
pump(0.5)
dlg.name_var.set("Games")
dlg.exts_var.set("sav, rom, iso2")
dlg._pick_glyph(5)
dlg._pick_colour(gui.ICON_COLOURS[5])
pump(0.3)
shot("small-window-add-file-type.png", dlg)
dlg._save()
app._finish_add_category(dlg)
pump()
check("Games saved with its logo", app.settings.category_icons.get("Games") == {"glyph": 5, "colour": gui.ICON_COLOURS[5]}
      and rules.load_settings().categories.get("Games") == ["sav", "rom", "iso2"])

filedialog.askopenfilename = lambda **k: str(PROJECT / "tidy_folders/assets/logo/24.png")
dlg = app._edit_category("Games", wait=False)
pump(0.3)
dlg._upload()
dlg._save()
app._finish_edit_category(dlg, "Games")
pump()
spec = app.settings.category_icons.get("Games", {})
check("an uploaded logo is copied into the app's own folder", spec.get("file", "").startswith("custom-")
      and (gui.icons_dir() / spec["file"]).exists())

dlg = app._edit_category("Music", wait=False)
pump(0.3)
shot("small-window-edit-music.png", dlg)
check("the file type window fits on screen", dlg.winfo_rooty() + dlg.winfo_height() <= dlg.winfo_screenheight())
dlg.destroy()
finish("SMALL WINDOW")
