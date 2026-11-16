"""When something unexpected goes wrong, the details are saved to error.log and you're told once,
instead of the click silently doing nothing (the .exe has no console)."""
from helpers import check, finish, pump, setup, use

work = setup("errors")

from tkinter import messagebox  # noqa: E402
from tidy_folders import __version__, crashlog, gui  # noqa: E402

shown = []
messagebox.showerror = lambda title, msg, **kw: shown.append(msg)

app = use(gui.App())
pump(0.6)
check(f"the sidebar shows the version ({__version__})",
      any(w.cget("text") == f"Version {__version__}" for w in app.sidebar.winfo_children()
          if w.winfo_class() == "Label"))


def broken_button():
    raise ValueError("pretend bug")


app.after(0, broken_button)
app.after(10, broken_button)  # a second one straight after: no second message
pump(0.5)
log = crashlog.log_path()
text = log.read_text(encoding="utf-8") if log.exists() else ""
check("the error was saved to error.log", "ValueError: pretend bug" in text and __version__ in text)
check("both errors were saved", text.count("ValueError: pretend bug") == 2)
check("you're told once, with where the details are", len(shown) == 1 and str(log) in shown[0])
check("the status line says so too", "error.log" in app.status_var.get())

app._run_in_background(lambda: 1 / 0, lambda result: None, "Testing")  # a failure while sorting
pump(1.0)
check("a failed background job is saved too", "ZeroDivisionError" in log.read_text(encoding="utf-8"))
check("...and explained", len(shown) == 2 and "division by zero" in shown[1] and str(log) in shown[1])
check("the app is still usable afterwards", not app.busy)
finish("ERRORS")
