"""The sorting animation: its frames and timings, playing once when you click the buddy, and during a
real Tidy up! (then the tongue face)."""
import time

from PIL import Image

from helpers import PROJECT, check, finish, make, pump, setup, use

work = setup("animation")
folder = work / "Downloads"
make(folder, ["a.pdf", "b.jpg", "c.mp3", "d.zip", "e.docx"])

from tkinter import messagebox  # noqa: E402
from tidy_folders import gui, rules  # noqa: E402

messagebox.askyesno = lambda *a, **k: True
rules.save_settings(rules.Settings(folders=[str(folder)]))


def record(seconds):
    """Watch the buddy for `seconds`; return [(ms since start, art)] each time it changes."""
    seen, start, last = [], time.perf_counter(), None
    while time.perf_counter() - start < seconds:
        app.update()
        name = app.mascot.image_name
        if name != last:
            seen.append((int((time.perf_counter() - start) * 1000), name))
            last = name
        time.sleep(0.005)
    return seen


app = use(gui.App())
pump(0.6)
frames = app._sorting_frames()
check(f"{len(frames)} frames with timings {[ms for _, ms in frames]}",
      len(frames) == 8 and [ms for _, ms in frames] == [130, 110, 110, 110, 110, 140, 150, 320])
first = Image.open(PROJECT / "tidy_folders/assets/sorting/Sorting_1.png").convert("RGBA")
hover = Image.open(PROJECT / "tidy_folders/assets/faces/surprised.png").convert("RGBA")
check("frame 1 is the surprised (hover) face, so it starts smoothly", first.tobytes() == hover.tobytes())

app._poke()  # click the buddy
seen = record(1.8)
shown = [art.split("/")[-1] for _, art in seen if art.startswith("sorting/")]
check("clicking the buddy plays all 8 frames once, in order", shown == [f"Sorting_{i}.png" for i in range(1, 9)])
check("then it goes back to its normal face", not seen[-1][1].startswith("sorting/") and not app.animating)

app.tidy_btn.invoke()
seen = record(3.0)
names = [a for _, a in seen]
check("Tidy up! plays the animation", sum(a.startswith("sorting/") for a in names) >= 8)
check("then celebrates with the tongue face",
      next((a for a in names if not a.startswith("sorting/")), None) == "faces/happy_tongue.png")
check("the files were moved", (folder / "Documents" / "a.pdf").exists() and app.result[0] == 5)
finish("ANIMATION")
