"""Choosing where a new folder goes: the new-folder symbol in the Preview, Folder location in the
file type window and the Other window, Reset, and a real Tidy up! and Undo."""
import os
import tkinter as tk

from helpers import check, click, finish, labels, make, pump, setup, shot, texts, use, wait_idle

work = setup("locations")
downloads, docs, elsewhere = work / "Downloads", work / "Documents", work / "Elsewhere"
inside = downloads / "Uni" / "2027"  # a place inside the folder being tidied
for d in (downloads, docs, elsewhere, work / "Stuff" / "3D Printing", inside):
    d.mkdir(parents=True)
make(downloads, ["part.stl", "bracket.3mf", "photo.jpg", "BOMBO.txt"])

from tkinter import messagebox  # noqa: E402
from tidy_folders import gui, rules  # noqa: E402

warnings = []
messagebox.showwarning = lambda title, msg, **kw: warnings.append(msg)
messagebox.askyesno = lambda *a, **k: True
answer = {"path": ""}
gui.filedialog.askdirectory = lambda **kw: answer["path"]  # stands in for the folder picker
s = rules.Settings(folders=[str(downloads)],
                   keyword_rules=[{"word": "BOMBO", "folder": str(work / "Projects" / "BOMBO")}])
s.categories["3D Printing"] = ["stl", "3mf"]
rules.save_settings(s)


def saved():
    return rules.load_settings().category_locations


def row(prefix):
    title = next(w for w in labels(app.panel) if str(w.cget("text")).startswith(prefix))
    return title.master.master


def badge(prefix):
    return next((w for w in labels(row(prefix)) if getattr(w, "image_name", "") == "new_folder"), None)


def pick(path, widget):
    answer["path"] = str(path)
    click(widget)


app = use(gui.App())
app.geometry("1120x900")
pump(1.0)
app._preview()
pump()
b = badge("3D Printing")
check("3D Printing row: a new-folder symbol you can click", b is not None and b.on_click and b.cget("cursor") == "hand2")
b.event_generate("<Enter>")
pump(0.6)
note = " ".join(t for top in b.winfo_children() if isinstance(top, tk.Toplevel) for t in texts(top))
check("its note says you can click it", "Click to choose where to make it." in note)
b.event_generate("<Leave>")

pick("", b)  # Cancel in the picker
check("cancelling the picker changes nothing", saved() == {})
pick(os.environ.get("SystemRoot", r"C:\Windows"), badge("3D Printing"))
check("a system folder is refused with a warning", warnings and saved() == {})
pick(docs, badge("3D Printing"))
check("choosing Documents saves it", saved() == {"3D Printing": str(docs)})
check("the plan sends 3D Printing files to Documents\\3D Printing", "→ Documents\\3D Printing\\" in texts())
check("still a new folder there, so the symbol stays", badge("3D Printing") is not None)
check("a Reset location link appears", "Reset location" in texts(row("3D Printing")))
shot("locations-chosen.png")

app.show_view("cats")
pump()
check("the Categories cards don't show folder locations",
      not any(t.startswith("Folder:") for t in texts(app.views["cats"])))

# The file type window: Folder location, with a folder-logo button
dlg = app._edit_category("3D Printing", wait=False)
pump()
check("the window shows where the folder goes", dlg.place.label.cget("text") == str(docs / "3D Printing")
      and dlg.place.reset_link.winfo_ismapped())
check("its Change button has the folder logo", str(dlg.place.button.icon) == str(app.sprites.get("faces/front.png", 1)))
shot("locations-file-type-window.png", dlg)
answer["path"] = str(inside)
dlg.place.button.command()
pump()
check("picking a place updates the window", dlg.place.label.cget("text") == str(inside / "3D Printing"))
dlg.name_var.set("3D Prints")
pump()
check("typing a new name updates the path shown", dlg.place.label.cget("text") == str(inside / "3D Prints"))
dlg.name_var.set("3D Printing")
dlg._save()
app._finish_edit_category(dlg, "3D Printing")
check("Save keeps the new place", saved() == {"3D Printing": str(inside)})

dlg = app._edit_category("3D Printing", wait=False)
pump()
click(dlg.place.reset_link)
check("Use the usual place: inside each folder you tidy",
      dlg.place.label.cget("text").startswith("Inside each folder you tidy") and not dlg.place.reset_link.winfo_ismapped())
dlg._save()
app._finish_edit_category(dlg, "3D Printing")
check("Save clears the place", saved() == {})

dlg = app._edit_category("3D Printing", wait=False)
answer["path"] = str(elsewhere)
dlg.place.button.command()
dlg.destroy()  # Cancel
check("Cancel throws the change away", saved() == {})

dlg = app._add_category(wait=False)
dlg.name_var.set("Laser")
dlg.exts_var.set("lbrn, dxf")
answer["path"] = str(elsewhere)
dlg.place.button.command()
dlg._save()
app._finish_add_category(dlg)
check("Add file type can set a place straight away", saved() == {"Laser": str(elsewhere)})
app.settings.category_locations.pop("Laser")
app._save()

# The Other card opens a window for where the Other folder goes
app._refresh_categories()
pump()
other = next(w for w in labels(app.views["cats"]) if w.cget("text") == "Other")
check("the Other card can be clicked", other.cget("cursor") == "hand2" and other.bind("<Button-1>"))
dlg = app._edit_other(wait=False)
pump()
check("the Other window starts at the usual place", dlg.place.label.cget("text").startswith("Inside each folder you tidy"))
answer["path"] = str(inside)
dlg.place.button.command()
dlg._save()
app._finish_edit_other(dlg)
check("Save keeps Other's place", saved() == {"Other": str(inside)})
dlg = app._edit_other(wait=False)
pump()
check("reopening shows it again", dlg.place.label.cget("text") == str(inside / "Other"))
shot("locations-other-window.png", dlg)
click(dlg.place.reset_link)
dlg._save()
app._finish_edit_other(dlg)
check("Use the usual place clears it", saved() == {})

app.show_view("sort")
app._preview()
pump()
pick(work / "Stuff" / "3D Printing", badge("3D Printing"))
check("picking a folder already called '3D Printing' uses it as is", saved() == {"3D Printing": str(work / "Stuff")})
check("it already exists, so no new-folder symbol", badge("3D Printing") is None)
click(next(w for w in labels(row("3D Printing")) if w.cget("text") == "Reset location"))
check("Reset location puts it back inside Downloads", saved() == {} and "→ 3D Printing\\" in texts())
pick(downloads, badge("3D Printing"))
check("choosing Downloads itself keeps the usual place", saved() == {})

pick(inside, badge("3D Printing"))
check("a place inside the folder being tidied: shows 2027\\3D Printing", "→ 2027\\3D Printing\\" in texts())
prints = [m for m in app.plans[str(downloads)] if m.category == "3D Printing"]
check("...and its full path is the new folder in 2027", {gui.dest_folder(m) for m in prints} == {inside / "3D Printing"})
check("...which doesn't exist yet, so the symbol shows", badge("3D Printing") is not None)
app.settings.mode = "type_month"
app._preview()
pump()
prints = [m for m in app.plans[str(downloads)] if m.category == "3D Printing"]
check("by type and month: still the 3D Printing folder in 2027",
      {gui.dest_folder(m) for m in prints} == {inside / "3D Printing"} and "→ 2027\\3D Printing\\" in texts())
app.settings.mode = "type"
app._preview()
pump()

pick(docs, badge("3D Printing"))
click(badge("Code words"))
check("the Code words symbol opens the list", app.expanded["word"] and badge("BOMBO  ·") is not None)
pick(elsewhere, badge("BOMBO  ·"))
check("BOMBO's folder moved to Elsewhere\\BOMBO", rules.load_settings().keyword_rules[0]["folder"]
      == str(elsewhere / "BOMBO"))

app.tidy_btn.invoke()
wait_idle()
check("Tidy up! put the 3D files in Documents\\3D Printing",
      (docs / "3D Printing" / "part.stl").exists() and (docs / "3D Printing" / "bracket.3mf").exists())
check("...BOMBO.txt in Elsewhere\\BOMBO", (elsewhere / "BOMBO" / "BOMBO.txt").exists())
check("...and the photo in Downloads\\Images", (downloads / "Images" / "photo.jpg").exists())
app._undo_last()
wait_idle()
check("Undo brings everything back and removes the new folders", (downloads / "part.stl").exists()
      and not (docs / "3D Printing").exists() and not (elsewhere / "BOMBO").exists())

dlg = app._edit_category("3D Printing", wait=False)
dlg.name_var.set("Prints")
dlg._save()
app._finish_edit_category(dlg, "3D Printing")
check("renaming the file type keeps its place", saved() == {"Prints": str(docs)})
finish("LOCATIONS")
