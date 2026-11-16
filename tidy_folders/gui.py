"""The Tidy Folders window, in a chunky pixel-art style built around the folder sprites."""
from __future__ import annotations

import os
import queue
import re
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import engine, startup
from . import tray as tray_mod
from .rules import APP_NAME, data_dir, default_categories, load_settings, normalize_ext, save_settings
from .watcher import AutoSorter

ASSETS = Path(__file__).resolve().parent / "assets"
SHOW_EVENT_NAME = "Local\\TidyFoldersShowWindow"  # a 2nd launch uses this to say "show yourself"

# Colours taken from the sprites
INK = "#212121"
YELLOW = "#FFD150"
YELLOW_LIGHT = "#FFDE73"
SHADE = "#E8BB48"
TAB = "#BA8200"
CREAM = "#FFF6D9"
PAGE = "#FFFDF7"
WHITE = "#FFFFFF"
MUTED = "#5C5446"
BLUE = "#1275B3"
LINE = "#F0E6C8"
HINT_BG = "#FFFBEB"
SKIPPED_BG = "#F4F1E8"
CHIP_BG = "#E8F3FB"
CHIP_FG = "#0D5A8A"
DISABLED_FACE = "#F1ECDD"
DISABLED_TEXT = "#9A9080"
DISABLED_EDGE = "#B9B0A0"
HOVER_FACE = {WHITE: CREAM, YELLOW: YELLOW_LIGHT, CREAM: WHITE}

MODE_LABELS = {
    "type": "File type  (Images, Documents, Music...)",
    "type_month": "File type, then month  (Images \\ 2026-11)",
    "month": "Month only  (2026-11)",
}
INTERVALS = [("15 seconds", 15), ("30 seconds", 30), ("1 minute", 60),
             ("5 minutes", 300), ("15 minutes", 900)]

_KNOWN_FOLDER_IDS = {
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
}


# ====================================================================== helpers

def known_folder(name: str) -> Path:
    """The real location of Downloads/Desktop/Documents (handles OneDrive and moved folders)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            guid = GUID()
            ctypes.oledll.ole32.CLSIDFromString(_KNOWN_FOLDER_IDS[name], ctypes.byref(guid))
            ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                          ctypes.byref(ptr)) == 0:
                path = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                if path:
                    return Path(path)
        except Exception:
            pass
    return Path.home() / name


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %Y  %I:%M %p")
    except (TypeError, ValueError):
        return str(iso)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def sentence(text: str) -> str:
    """End with a full stop, unless the text already ends in "…"."""
    return text if text.endswith("…") else text + "."


def join_names(names: list[str]) -> str:
    names = [n if len(n) <= 24 else n[:22] + "…" for n in names]  # display only
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]}, {names[1]} and {plural(len(names) - 2, 'more folder')}"


def dest_folder(move: engine.Move) -> Path:
    """The folder a move puts its file in, as you'd see it in File Explorer: 'Downloads\\Images',
    the course / code-word folder, or a file type's folder somewhere else ('Documents\\3D Printing')."""
    parent = Path(move.dst).parent
    if move.rule:
        return parent
    # 'Images\photo.jpg', or 'Images\2026-11\photo.jpg' when sorting by type and month: the file type's
    # folder, wherever it is (inside the tidied folder, or a place chosen for it, even inside that folder).
    # Sorting by month only: the month folder.
    return parent.parent if parent.name != move.category and parent.parent.name == move.category else parent


def dest_label(move: engine.Move, folder: str) -> str:
    """Short name for where a move goes: 'Images', '2026\\Semester 1\\ELECTENG 101' or 'Documents\\Finance'."""
    target = dest_folder(move)
    if move.rule or target.parent != Path(folder):
        keep = 3 if move.rule == "course" else 2  # courses: show the year too
        parts = [p for p in target.parts[-keep:] if p not in (target.anchor, "\\", "/")]
        return "\\".join(parts) or str(target)
    return target.name


HAPPY_UP_TO = 2   # this many loose files (or fewer) still gets a smile
MESSY_FROM = 10   # this many or more: overwhelmed


def face_for(count: int) -> str:
    if count <= HAPPY_UP_TO:
        return "faces/happy.png"
    return "faces/sad.png" if count < MESSY_FROM else "faces/dead.png"


def fit_text(text: str, font: tkfont.Font, max_px: int, side: str = "end") -> str:
    """Display-only: shorten `text` with "…" so it fits `max_px` (cuts the end, or the start for paths)."""
    if max_px <= 0 or font.measure(text) <= max_px:
        return text
    while text and font.measure(("…" + text) if side == "start" else (text + "…")) > max_px:
        text = text[1:] if side == "start" else text[:-1]
    return ("…" + text) if side == "start" else (text + "…")


def wrapped_lines(text: str, font: tkfont.Font, width: int) -> int:
    """How many lines `text` takes when wrapped at `width` pixels (long words break mid-word)."""
    count = 0
    for paragraph in text.split("\n"):
        lines, line = 1, ""
        for word in paragraph.split(" "):
            trial = f"{line} {word}" if line else word
            if font.measure(trial) <= width:
                line = trial
                continue
            if line:
                lines += 1
            while len(word) > 1 and font.measure(word) > width:
                k = len(word)
                while k > 1 and font.measure(word[:k]) > width:
                    k -= 1
                word = word[k:]
                lines += 1
            line = word
        count += lines
    return count


_fonts_loaded = False


def load_bundled_fonts() -> None:
    """Make the bundled pixel font available to this program only (nothing is installed)."""
    global _fonts_loaded
    if _fonts_loaded or sys.platform != "win32":
        return
    _fonts_loaded = True
    import ctypes
    for font_file in (ASSETS / "fonts").glob("*.ttf"):
        try:
            ctypes.windll.gdi32.AddFontResourceExW(str(font_file), 0x10, 0)  # FR_PRIVATE
        except Exception:
            pass


class Sprites:
    """Loads pixel art and scales it up by whole numbers, so pixels stay crisp."""

    def __init__(self, master: tk.Misc, scale: float):
        self.master, self.scale = master, scale
        self._cache: dict[tuple[str, int, bool], tk.PhotoImage] = {}

    def zoom_for(self, base: float) -> int:
        return max(1, int(base * self.scale + 0.5))

    def get(self, rel: str, base_zoom: float = 1, trim: bool = False) -> tk.PhotoImage:
        """`rel` is a path inside assets/, or a full path (e.g. an uploaded logo).
        `trim` drops see-through edges, so a border drawn around the picture hugs it."""
        zoom = self.zoom_for(base_zoom)
        key = (rel, zoom, trim)
        if key not in self._cache:
            path = Path(rel) if Path(rel).is_absolute() else ASSETS / rel
            try:
                img = tk.PhotoImage(master=self.master, file=str(path))
            except tk.TclError:  # missing art: a blank stand-in rather than a crash
                img = tk.PhotoImage(master=self.master, width=24, height=21)
            self._cache[key] = self._finish(img, zoom, trim)
        return self._cache[key]

    def compose(self, glyph: str, colour: str, base_zoom: float = 1, trim: bool = False) -> tk.PhotoImage:
        """A file-type logo: a white symbol (assets/glyphs/<glyph>.png, 16x14) on a coloured
        tile, laid out like the built-in category icons (24x21, with a see-through strip
        2px wide down each side; `trim` drops those strips)."""
        zoom = self.zoom_for(base_zoom)
        key = (f"compose:{glyph}:{colour}", zoom, trim)
        if key not in self._cache:
            img = tk.PhotoImage(master=self.master, width=24, height=21)
            img.put(colour, to=(2, 0, 22, 21))
            try:
                symbol = tk.PhotoImage(master=self.master, file=str(ASSETS / "glyphs" / f"{glyph}.png"))
                img.tk.call(img, "copy", symbol, "-to", 4, 3, "-compositingrule", "overlay")
            except tk.TclError:
                pass
            self._cache[key] = self._finish(img, zoom, trim)
        return self._cache[key]

    def _finish(self, img: tk.PhotoImage, zoom: int, trim: bool) -> tk.PhotoImage:
        if trim:
            img = self._trimmed(img)
        return img.zoom(zoom) if zoom > 1 else img

    def _trimmed(self, img: tk.PhotoImage) -> tk.PhotoImage:
        """`img` cut down to the box around its visible (not see-through) pixels."""
        w, h = img.width(), img.height()
        seen = lambda x, y: not img.transparency_get(x, y)  # noqa: E731
        cols = [x for x in range(w) if any(seen(x, y) for y in range(h))]
        rows = [y for y in range(h) if any(seen(x, y) for x in range(w))]
        if not cols or (len(cols), len(rows)) == (w, h):
            return img
        x1, y1, x2, y2 = cols[0], rows[0], cols[-1] + 1, rows[-1] + 1
        out = tk.PhotoImage(master=self.master, width=x2 - x1, height=y2 - y1)
        out.tk.call(out, "copy", img, "-from", x1, y1, x2, y2)
        return out


# Plan rows that gather every course / every code word into one row, with a dropdown.
BUNDLES = {
    "course": {"title": "Courses", "noun": "course", "icon": "Course", "all": engine.ALL_COURSES,
               "dest_noun": "course folder", "tip": "Course files go to their own course folders:"},
    "word": {"title": "Code words", "noun": "code word", "icon": "Code word", "all": engine.ALL_WORDS,
             "dest_noun": "folder", "tip": "Files with a code word in their name go to:"},
}

ICON_COLOURS = ["#C23B4A", "#D2582A", "#E09F00", "#2E8A57", "#0E8A8A",
                "#1275B3", "#3949AB", "#7B4FA8", "#C74183"]  # white symbols stay readable on all of them
                                                             # (the yellow is the folder tab's amber)
UPLOAD_TILE = "#7A8086"


def icons_dir() -> Path:
    folder = data_dir() / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def import_logo(source: str, master: tk.Misc) -> str:
    """Copy a picture the user picked into the app's icons folder, fitted to 24x21. Returns its file name."""
    name = f"custom-{uuid.uuid4().hex[:8]}.png"
    target = icons_dir() / name
    try:
        from PIL import Image
        im = Image.open(source).convert("RGBA")
        if im.size != (24, 21):
            im.thumbnail((24, 21), Image.NEAREST if max(im.size) <= 48 else Image.LANCZOS)
            canvas = Image.new("RGBA", (24, 21), (0, 0, 0, 0))
            canvas.paste(im, ((24 - im.width) // 2, (21 - im.height) // 2), im)
            im = canvas
        im.save(target)
    except ImportError:  # no Pillow (running from source without it): PNG/GIF, shrunk by whole numbers
        img = tk.PhotoImage(master=master, file=source)
        factor = max(1, -(-img.width() // 24), -(-img.height() // 21))
        (img.subsample(factor) if factor > 1 else img).write(str(target), format="png")
    return name


# ====================================================================== pixel widgets

class PixelButton(tk.Canvas):
    """Chunky pixel button: thick ink outline and a hard shadow it sinks into when pressed."""

    def __init__(self, parent, text, command=None, *, app, bg, face=WHITE, font=None,
                 icon=None, width=None, anchor="center", padx=14, pady=6):
        s = app.px
        self.app, self.text, self.command = app, text, command
        self.font = font or app.f_btn
        self.face, self.icon, self.anchor = face, icon, anchor
        self.b, self.d, self.padx = s(3), s(4), s(padx)
        tw = self.font.measure(text) if text else 0
        self.iw = (icon.width() + (s(10) if text else 0)) if icon else 0
        ih = icon.height() if icon else 0
        self.w = width or (tw + self.iw + 2 * self.padx + 2 * self.b)
        self.h = max(self.font.metrics("linespace"), ih) + 2 * s(pady) + 2 * self.b
        super().__init__(parent, width=self.w + self.d, height=self.h + self.d, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.enabled, self.hover, self.pressed, self.focused = True, False, False, False
        for seq, fn in (("<Enter>", self._enter), ("<Leave>", self._leave),
                        ("<ButtonPress-1>", self._press), ("<ButtonRelease-1>", self._release),
                        ("<FocusIn>", lambda e: self._focus(True)), ("<FocusOut>", lambda e: self._focus(False)),
                        ("<KeyPress-space>", self._key), ("<KeyPress-Return>", self._key)):
            self.bind(seq, fn)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        off = self.d if (self.pressed and self.enabled) else 0
        if not off:
            self.create_rectangle(self.d, self.d, self.w + self.d, self.h + self.d,
                                  fill=INK if self.enabled else DISABLED_EDGE, outline="")
        self.create_rectangle(off, off, off + self.w, off + self.h,
                              fill=INK if self.enabled else DISABLED_EDGE, outline="")
        face = self.face
        if not self.enabled:
            face = DISABLED_FACE
        elif self.hover and not self.pressed:
            face = HOVER_FACE.get(self.face, self.face)
        self.create_rectangle(off + self.b, off + self.b, off + self.w - self.b, off + self.h - self.b,
                              fill=face, outline="")
        cy = off + self.h / 2
        content = self.iw + (self.font.measure(self.text) if self.text else 0)
        x = off + (self.w - content) / 2 if self.anchor == "center" else off + self.b + self.padx
        if self.icon:
            self.create_image(x, cy, image=self.icon, anchor="w")
            x += self.iw
        if self.text:
            self.create_text(x, cy, text=self.text, font=self.font, anchor="w",
                             fill=INK if self.enabled else DISABLED_TEXT)
        if self.focused and self.enabled:
            g = self.b + self.app.px(3)
            self.create_rectangle(off + g, off + g, off + self.w - g, off + self.h - g,
                                  outline=BLUE, dash=(2, 2))

    def _enter(self, _e):
        self.hover = True
        self._draw()

    def _leave(self, _e):
        self.hover = self.pressed = False
        self._draw()

    def _press(self, _e):
        if self.enabled:
            self.pressed = True
            self._draw()

    def _release(self, e):
        was = self.pressed
        self.pressed = False
        self._draw()
        inside = 0 <= e.x <= self.w + self.d and 0 <= e.y <= self.h + self.d
        if was and inside:
            self.invoke()

    def _focus(self, on: bool):
        self.focused = on
        self._draw()

    def _key(self, _e):
        self.invoke()

    def invoke(self) -> None:
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, on: bool) -> None:
        if on != self.enabled:
            self.enabled = on
            self.configure(cursor="hand2" if on else "arrow", takefocus=1 if on else 0)
            self._draw()

    def set_face(self, face: str) -> None:
        self.face = face
        self._draw()


class SpriteButton(tk.Canvas):
    """The Tidy up! button: drawn with the button sprites, words written on top."""

    def __init__(self, parent, text, command, *, app, bg, base_zoom=3):
        self.app, self.command = app, command
        self.zoom = app.sprites.zoom_for(base_zoom)
        self.imgs = {k: app.sprites.get(f"button/{k}.png", base_zoom) for k in ("normal", "hover", "pressed")}
        w, h = self.imgs["normal"].width(), self.imgs["normal"].height()
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self.img = self.create_image(0, 0, image=self.imgs["normal"], anchor="nw")
        self.cx, self.cy = 23 * self.zoom, 7 * self.zoom  # centre of the button face in the sprite
        self.label = self.create_text(self.cx, self.cy, text=text, font=app.f_big_btn, fill=INK)
        self.ring = None
        self.hover = self.pressed = False
        self.enabled = True
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<KeyPress-space>", lambda e: self.invoke())
        self.bind("<KeyPress-Return>", lambda e: self.invoke())
        self.bind("<FocusIn>", lambda e: self._ring(True))
        self.bind("<FocusOut>", lambda e: self._ring(False))

    def _set(self, hover=None, pressed=None):
        if hover is not None:
            self.hover = hover
        if pressed is not None:
            self.pressed = pressed and self.enabled
        state = "pressed" if self.pressed else ("hover" if self.hover and self.enabled else "normal")
        self.itemconfigure(self.img, image=self.imgs[state])
        shift = 2 * self.zoom if self.pressed else 0
        self.coords(self.label, self.cx + shift, self.cy + shift)

    def _release(self, e):
        was = self.pressed
        self._set(pressed=False)
        if was and 0 <= e.x <= int(self["width"]) and 0 <= e.y <= int(self["height"]):
            self.invoke()

    def _ring(self, on):
        if self.ring:
            self.delete(self.ring)
            self.ring = None
        if on:
            z = self.zoom
            self.ring = self.create_rectangle(2 * z, 2 * z, 44 * z, 12 * z, outline=BLUE, dash=(2, 2))

    def invoke(self) -> None:
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self.itemconfigure(self.label, fill=INK if on else DISABLED_TEXT)
        self.configure(cursor="hand2" if on else "arrow")


class PixelSwitch(tk.Label):
    """The on/off switch for automatic sorting, drawn with the switch sprites."""

    def __init__(self, parent, *, app, bg, command, on=False):
        self.imgs = {True: app.sprites.get("switch/on.png", 3), False: app.sprites.get("switch/off.png", 3)}
        super().__init__(parent, image=self.imgs[on], bg=bg, bd=0, cursor="hand2", takefocus=1,
                         highlightthickness=app.px(2), highlightbackground=bg, highlightcolor=BLUE)
        self.on, self.command = on, command
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<KeyPress-space>", lambda e: self.command())

    def set(self, on: bool) -> None:
        self.on = on
        self.configure(image=self.imgs[on])


class ScrollFrame(tk.Frame):
    """A frame whose contents scroll (the window routes the mouse wheel to it)."""

    def __init__(self, parent, *, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

    def scroll(self, steps: int) -> None:
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(steps, "units")

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)


class FlowFrame(tk.Frame):
    """Lays its items out left to right and wraps onto new lines to fit its width."""

    def __init__(self, parent, *, bg, gap=8):
        super().__init__(parent, bg=bg, height=1)
        self.items: list[tk.Widget] = []
        self.gap = gap
        self.bind("<Configure>", lambda e: self._layout())

    def clear(self) -> None:
        for widget in self.items:
            widget.destroy()
        self.items = []

    def add(self, widget: tk.Widget) -> None:
        self.items.append(widget)
        self.after_idle(self._layout)

    def _layout(self) -> None:
        if not self.winfo_exists():
            return
        width = max(self.winfo_width(), 50)
        x = y = line = 0
        for widget in self.items:
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if x and x + w > width:
                x, y, line = 0, y + line + 2, 0
            widget.place(x=x, y=y)
            x += w + self.gap
            line = max(line, h)
        if int(self["height"]) != y + line:
            self.configure(height=max(1, y + line))


def shadow_card(parent, app, *, bg, fill=WHITE, border=3, depth=4):
    """A box with a thick ink outline and a hard offset shadow. Returns (holder, inside)."""
    holder = tk.Frame(parent, bg=bg)
    holder.columnconfigure(0, weight=1)
    holder.rowconfigure(0, weight=1)
    d = app.px(depth)
    tk.Frame(holder, bg=INK).grid(row=0, column=0, sticky="nsew", padx=(d, 0), pady=(d, 0))
    card = tk.Frame(holder, bg=fill, highlightthickness=app.px(border), highlightbackground=INK,
                    highlightcolor=INK)
    card.grid(row=0, column=0, sticky="nsew", padx=(0, d), pady=(0, d))
    card.lift()
    return holder, card


class Tooltip:
    """A small note that appears when the mouse rests on a widget."""

    def __init__(self, widget: tk.Widget, text: str, *, app, delay: int = 300):
        self.widget, self.text, self.app, self.delay = widget, text, app, delay
        self.tip: tk.Toplevel | None = None
        self.job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self.job = self.widget.after(self.delay, self.show)

    def _cancel(self) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def show(self) -> None:
        if self.tip or not self.widget.winfo_exists():
            return
        p = self.app.px
        self.tip = tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        box = tk.Frame(tip, bg=CREAM, highlightthickness=p(2), highlightbackground=INK)
        box.pack()
        tk.Label(box, text=self.text, font=self.app.f_small, bg=CREAM, fg=INK, justify="left",
                 wraplength=p(340)).pack(padx=p(8), pady=p(5))
        tip.update_idletasks()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() - tip.winfo_width()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + p(4)
        x = max(4, min(x, tip.winfo_screenwidth() - tip.winfo_width() - 4))
        tip.geometry(f"+{x}+{y}")

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def link(parent, text, command, *, app, bg):
    label = tk.Label(parent, text=text, font=app.f_link, fg=BLUE, bg=bg, cursor="hand2")
    label.bind("<Button-1>", lambda e: command())
    return label


# ====================================================================== category dialog

class CategoryDialog(tk.Toplevel):
    """Add or edit one file type: its folder name, its extensions and its logo.

    The logo picker is a 3x3 grid: 8 ready-made symbols (assets/glyphs/1-8.png) and an
    "upload your own" tile, next to 9 colours to put the symbol on.
    """

    def __init__(self, app, title, validate, name="", exts="", can_remove=False, icon=None, wait=True):
        super().__init__(app)
        p = app.px
        self.app = app
        self.title(title)
        self.transient(app)
        self.resizable(False, False)
        self.configure(bg=PAGE)
        self.result: tuple | None = None
        self._validate = validate
        self.original_name = name
        self.icon_changed = False
        self.glyph = icon.get("glyph") if icon else None
        self.file = icon.get("file") if icon else None
        self.colour = (icon or {}).get("colour") or ICON_COLOURS[0]
        if not icon and not name:  # a brand-new file type starts with a logo already picked
            self.glyph = 1
            self.colour = ICON_COLOURS[len(app.settings.category_icons) % len(ICON_COLOURS)]
            self.icon_changed = True

        body = tk.Frame(self, bg=PAGE)
        body.pack(fill="both", expand=True, padx=p(20), pady=p(18))
        tk.Label(body, text="Folder name", font=app.f_body_b, bg=PAGE, fg=INK).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=name)
        name_entry = ttk.Entry(body, textvariable=self.name_var, width=40, font=app.f_body)
        name_entry.grid(row=1, column=0, sticky="we", pady=(p(4), p(14)))
        tk.Label(body, text="File types, separated by commas (for example: jpg, png, gif)",
                 font=app.f_body_b, bg=PAGE, fg=INK).grid(row=2, column=0, sticky="w")
        self.exts_var = tk.StringVar(value=exts)
        ttk.Entry(body, textvariable=self.exts_var, width=56, font=app.f_body).grid(
            row=3, column=0, sticky="we", pady=(p(4), p(16)))

        tk.Label(body, text="Logo", font=app.f_body_b, bg=PAGE, fg=INK).grid(row=4, column=0, sticky="w")
        tk.Label(body, text="Pick a symbol and a colour, or upload your own picture (24×21 pixel art looks best).",
                 font=app.f_small, bg=PAGE, fg=MUTED).grid(row=5, column=0, sticky="w", pady=(0, p(6)))
        picker = tk.Frame(body, bg=PAGE)
        picker.grid(row=6, column=0, sticky="w", pady=(0, p(18)))
        symbols = tk.Frame(picker, bg=PAGE)
        symbols.pack(side="left")
        self.tiles: list[tk.Label] = []
        for i in range(9):
            tile = tk.Label(symbols, bg=PAGE, bd=0, cursor="hand2", highlightthickness=p(3),
                            highlightbackground=PAGE)
            tile.grid(row=i // 3, column=i % 3, padx=p(2), pady=p(2))
            tile.bind("<Button-1>", (lambda e, g=i + 1: self._pick_glyph(g)) if i < 8 else (lambda e: self._upload()))
            self.tiles.append(tile)
        tk.Label(symbols, text="↑ upload your own", font=app.f_small, bg=PAGE, fg=MUTED).grid(
            row=3, column=1, columnspan=2, sticky="e")
        colours = tk.Frame(picker, bg=PAGE)
        colours.pack(side="left", padx=(p(18), 0), anchor="n")
        self.swatches: list[tuple[tk.Canvas, str]] = []
        size = p(30)
        for i, colour in enumerate(ICON_COLOURS):
            sw = tk.Canvas(colours, width=size, height=size, bg=PAGE, highlightthickness=0, cursor="hand2")
            sw.grid(row=i // 3, column=i % 3, padx=p(3), pady=p(3))
            sw.bind("<Button-1>", lambda e, c=colour: self._pick_colour(c))
            self.swatches.append((sw, colour))
        preview = tk.Frame(picker, bg=PAGE)
        preview.pack(side="left", padx=(p(22), 0), anchor="n")
        tk.Label(preview, text="Preview", font=app.f_small_b, bg=PAGE, fg=MUTED).pack(anchor="w")
        self.preview = tk.Label(preview, bg=PAGE)
        self.preview.pack(anchor="w", pady=(p(4), p(4)))
        if name and (ASSETS / "categories" / f"{name}.png").exists():
            link(preview, "Use the original logo", self._use_original, app=app, bg=PAGE).pack(anchor="w")

        buttons = tk.Frame(body, bg=PAGE)
        buttons.grid(row=7, column=0, sticky="we")
        if can_remove:
            PixelButton(buttons, "Remove", self._remove, app=app, bg=PAGE).pack(side="left")
        PixelButton(buttons, "Cancel", self.destroy, app=app, bg=PAGE).pack(side="right")
        PixelButton(buttons, "Save", self._save, app=app, bg=PAGE, face=YELLOW).pack(side="right", padx=(0, p(10)))
        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())
        self._refresh_picker()

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        name_entry.focus_set()
        if wait:  # tests drive the window without waiting on it
            self.grab_set()
            self.wait_window()

    # --- logo picker
    def icon_spec(self) -> dict | None:
        if self.file:
            return {"file": self.file}
        return {"glyph": self.glyph, "colour": self.colour} if self.glyph else None

    def _refresh_picker(self) -> None:
        app = self.app
        # The "chosen" box is blue, or ink on blue tiles (where blue wouldn't show).
        ring = INK if self.colour.upper() == BLUE.upper() else BLUE
        for i, tile in enumerate(self.tiles):  # trimmed, so the box hugs the tile
            if i < 8:
                tile.configure(image=app.sprites.compose(str(i + 1), self.colour, 2, trim=True))
                chosen = not self.file and self.glyph == i + 1
            else:
                tile.configure(image=app.icon_image({"file": self.file}, base_zoom=2, trim=True) if self.file
                               else app.sprites.compose("upload", UPLOAD_TILE, 2, trim=True))
                chosen = bool(self.file)
            tile.configure(highlightbackground=(ring if i < 8 else BLUE) if chosen else PAGE)
        b = app.px(3)
        for sw, colour in self.swatches:
            sw.delete("all")
            size = int(sw["width"])
            if colour == self.colour and self.glyph and not self.file:
                sw.create_rectangle(0, 0, size, size, fill=INK, outline="")
            sw.create_rectangle(b, b, size - b, size - b, fill=colour, outline="")
        self.preview.configure(image=app.icon_image(self.icon_spec(), self.original_name, 4))

    def _pick_glyph(self, glyph: int) -> None:
        self.glyph, self.file, self.icon_changed = glyph, None, True
        self._refresh_picker()

    def _pick_colour(self, colour: str) -> None:
        self.colour, self.file, self.icon_changed = colour, None, True
        if not self.glyph:
            self.glyph = 1
        self._refresh_picker()

    def _upload(self) -> None:
        source = filedialog.askopenfilename(parent=self, title="Choose a picture for this file type",
                                            filetypes=[("Pictures", "*.png *.gif *.jpg *.jpeg *.bmp"),
                                                       ("All files", "*.*")])
        if not source:
            return
        try:
            self.file = import_logo(source, self)
        except Exception as err:
            messagebox.showwarning(APP_NAME, f"That picture couldn't be used:\n\n{err}", parent=self)
            return
        self.glyph, self.icon_changed = None, True
        self._refresh_picker()

    def _use_original(self) -> None:
        self.glyph, self.file, self.icon_changed = None, None, True
        self._refresh_picker()

    def _save(self) -> None:
        name = self.name_var.get().strip()
        raw = re.split(r"[,;\s]+", self.exts_var.get())
        exts = list(dict.fromkeys(e for e in (normalize_ext(x) for x in raw) if e))
        error = self._validate(name, exts)
        if error:
            messagebox.showwarning(APP_NAME, error, parent=self)
            return
        self.result = ("save", name, exts)
        self.destroy()

    def _remove(self) -> None:
        self.result = ("remove",)
        self.destroy()


class WordRuleDialog(tk.Toplevel):
    """Small window for adding a code word and the folder its files go to."""

    def __init__(self, app, validate):
        super().__init__(app)
        p = app.px
        self.app, self._validate = app, validate
        self.result: tuple[str, str] | None = None
        self.title("Add code word")
        self.transient(app)
        self.resizable(False, False)
        self.configure(bg=PAGE)

        body = tk.Frame(self, bg=PAGE)
        body.pack(fill="both", expand=True, padx=p(20), pady=p(18))
        tk.Label(body, text="Code word (any file with this in its name)", font=app.f_body_b, bg=PAGE,
                 fg=INK).grid(row=0, column=0, columnspan=2, sticky="w")
        self.word_var = tk.StringVar()
        word_entry = ttk.Entry(body, textvariable=self.word_var, width=40, font=app.f_body)
        word_entry.grid(row=1, column=0, columnspan=2, sticky="we", pady=(p(4), p(14)))
        tk.Label(body, text="Send those files to", font=app.f_body_b, bg=PAGE, fg=INK).grid(
            row=2, column=0, columnspan=2, sticky="w")
        self.folder_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.folder_var, width=52, font=app.f_body, state="readonly").grid(
            row=3, column=0, sticky="we", pady=(p(4), p(18)))
        PixelButton(body, "Choose...", self._choose, app=app, bg=PAGE, pady=3).grid(
            row=3, column=1, sticky="w", padx=(p(10), 0), pady=(p(4), p(18)))
        buttons = tk.Frame(body, bg=PAGE)
        buttons.grid(row=4, column=0, columnspan=2, sticky="we")
        PixelButton(buttons, "Cancel", self.destroy, app=app, bg=PAGE).pack(side="right")
        PixelButton(buttons, "Save", self._save, app=app, bg=PAGE, face=YELLOW).pack(side="right", padx=(0, p(10)))
        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        word_entry.focus_set()
        self.grab_set()
        self.wait_window()

    def _choose(self) -> None:
        path = filedialog.askdirectory(parent=self, mustexist=True, title="Where should these files go?")
        if path:
            self.folder_var.set(str(Path(path)))

    def _save(self) -> None:
        word, folder = self.word_var.get().strip(), self.folder_var.get().strip()
        error = self._validate(word, folder)
        if error:
            messagebox.showwarning(APP_NAME, error, parent=self)
            return
        self.result = (word, folder)
        self.destroy()


# ====================================================================== the window

class App(tk.Tk):
    def __init__(self, start_hidden: bool = False) -> None:
        load_bundled_fonts()
        super().__init__()
        if start_hidden:
            self.withdraw()  # opened at sign-in: live in the tray, no window
        self.title(APP_NAME)
        self.icon_path = ASSETS / "icon.ico"
        if self.icon_path.exists():
            try:
                self.iconbitmap(default=str(self.icon_path))
            except tk.TclError:
                pass
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96)  # follow Windows display scaling
        self.geometry(f"{self.px(1120)}x{self.px(790)}")
        self.minsize(self.px(940), self.px(680))
        self.configure(bg=PAGE)

        self.settings = load_settings()
        self.history = engine.History()
        self.events: queue.Queue = queue.Queue()  # work for the UI thread
        self.auto: AutoSorter | None = None
        self.busy = False
        self.sprites = Sprites(self, self.scale)
        self.view = "sort"
        self.phase = "idle"  # idle | preview | done | problem
        self.counts: dict[str, int | None] = {}
        self.plans: dict[str, list[engine.Move]] = {}
        self.result: tuple[int, list[str]] = (0, [])
        self.celebrating = False
        self.mascot_hover = False
        self.expanded = {kind: False for kind in BUNDLES}  # the Courses / Code words dropdowns in the preview
        self.animating = False          # the sorting animation is playing on the buddy
        self._anim_frames: list[tuple[str, int]] | None = None
        self._anim_index = 0
        self._anim_stop = False         # finish the current loop, then stop
        self._anim_finish = None        # what to do once it has stopped
        self.card_widgets: dict[str, tuple[tk.Label, tk.Label]] = {}
        self.tray = self._create_tray()

        self._init_fonts()
        self._init_style()
        self._build()
        if self.settings.auto_sort and self.settings.auto_armed:
            self._start_auto()
        self._update_auto_label()
        self._scan()
        self._rebuild_folder_cards()
        self._show_panel()
        self._refresh_categories()
        self._refresh_history()
        self._update_mood()
        self._sorting_frames()  # preload the animation
        if self.tray:
            self.tray.start()
        elif start_hidden:
            self.deiconify()  # no tray available, so show the window after all
        try:
            startup.refresh_path()  # the .exe may have been moved since start-up was turned on
        except OSError:
            pass
        self._listen_for_show_requests()
        self._set_window_icons()
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.after(150, self._drain_events)
        self.after(8000, self._periodic)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def px(self, n: float) -> int:
        return max(1, int(n * self.scale + 0.5))

    def _set_window_icons(self) -> None:
        """Give Windows sizes it can shrink cleanly, so the taskbar icon stays crisp pixel art.

        The large icon is the logo at 2x the taskbar size (Windows halves it exactly);
        the small one (title bar) is the 16x16 logo scaled to the system size.
        """
        if sys.platform != "win32" or not self.icon_path.exists():
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                          ctypes.c_int, ctypes.c_int, wintypes.UINT)
            user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            user32.GetParent.restype = wintypes.HWND
            self.update_idletasks()
            hwnd = user32.GetParent(self.winfo_id())
            if not hwnd:
                return
            big = 48 if self.scale < 1.5 else 72 if self.scale < 2 else 96   # 2x the taskbar size
            small = self.px(16)
            for which, size in ((1, big), (0, small)):  # ICON_BIG, ICON_SMALL
                handle = user32.LoadImageW(None, str(self.icon_path), 1, size, size, 0x10)  # LR_LOADFROMFILE
                if handle:
                    user32.SendMessageW(hwnd, 0x0080, which, handle)  # WM_SETICON
        except Exception:
            pass  # keep the default icons

    # ------------------------------------------------------------------ look

    def _init_fonts(self) -> None:
        families = {f.lower() for f in tkfont.families(self)}
        pixel = "Pixelify Sans" if "pixelify sans" in families else None
        body = "Segoe UI" if "segoe ui" in families else tkfont.nametofont("TkDefaultFont").actual("family")
        head = pixel or body
        self.has_pixel_font = pixel is not None
        F = lambda fam, size, weight="normal", **kw: tkfont.Font(self, family=fam, size=size, weight=weight, **kw)
        self.f_title = F(head, 20, "bold")
        self.f_h2 = F(head, 15, "bold")
        self.f_mood = F(head, 17, "bold")
        self.f_big_btn = F(head, 14, "bold")
        self.f_body = F(body, 10)
        self.f_body_b = F(body, 10, "bold")
        self.f_btn = F(body, 10, "bold")
        self.f_name = F(body, 12, "bold")
        self.f_small = F(body, 9)
        self.f_small_b = F(body, 9, "bold")
        self.f_link = F(body, 9, underline=True)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=body, size=10)
        self.option_add("*TCombobox*Listbox.font", self.f_body)

    def _init_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=self.f_body, background=PAGE, foreground=INK)
        style.configure("TCombobox", fieldbackground=WHITE, background=YELLOW, foreground=INK,
                        arrowcolor=INK, bordercolor=INK, lightcolor=WHITE, darkcolor=WHITE,
                        padding=self.px(4), arrowsize=self.px(14))
        style.map("TCombobox", fieldbackground=[("readonly", WHITE)],
                  selectbackground=[("readonly", WHITE)], selectforeground=[("readonly", INK)],
                  background=[("active", YELLOW_LIGHT)])
        for name, bg in (("Cream.TCheckbutton", CREAM), ("Page.TCheckbutton", PAGE)):
            style.configure(name, background=bg, foreground=INK, font=self.f_body,
                            indicatorbackground=WHITE, indicatorforeground=INK,
                            upperbordercolor=INK, lowerbordercolor=INK, focuscolor=bg)
            style.map(name, background=[("active", bg)],
                      indicatorbackground=[("selected", YELLOW), ("pressed", CREAM)],
                      foreground=[("disabled", DISABLED_TEXT)])
        style.configure("Vertical.TScrollbar", background=YELLOW, troughcolor=CREAM, bordercolor=INK,
                        arrowcolor=INK, lightcolor=YELLOW, darkcolor=SHADE, gripcount=0)
        style.map("Vertical.TScrollbar", background=[("active", YELLOW_LIGHT)])
        style.configure("TEntry", fieldbackground=WHITE, bordercolor=INK, lightcolor=WHITE,
                        darkcolor=WHITE, padding=self.px(5))

    def category_sprite(self, name: str, base_zoom: float = 2) -> tk.PhotoImage:
        """A file type's logo: the one picked for it, else its built-in art, else the plain folder."""
        return self.icon_image(self.settings.category_icons.get(name), name, base_zoom)

    def icon_image(self, spec: dict | None, name: str = "", base_zoom: float = 2,
                   trim: bool = False) -> tk.PhotoImage:
        if spec and spec.get("file"):
            path = icons_dir() / spec["file"]
            if path.exists():
                return self.sprites.get(str(path), base_zoom, trim)
        elif spec and spec.get("glyph"):
            return self.sprites.compose(str(spec["glyph"]), spec.get("colour", ICON_COLOURS[0]), base_zoom, trim)
        art = f"categories/{name}.png"
        return self.sprites.get(art if name and (ASSETS / art).exists() else "faces/front.png", base_zoom, trim)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        p = self.px
        self.status_var = tk.StringVar(value="Ready.")
        status = tk.Frame(self, bg=PAGE)
        status.pack(side="bottom", fill="x")
        tk.Frame(status, bg=INK, height=p(3)).pack(fill="x")
        tk.Label(status, textvariable=self.status_var, font=self.f_small, fg=MUTED, bg=PAGE,
                 anchor="w").pack(fill="x", padx=p(16), pady=p(5))

        body = tk.Frame(self, bg=PAGE)
        body.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(body, bg=CREAM, width=p(290))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(body, bg=INK, width=p(3)).pack(side="left", fill="y")
        self.main = tk.Frame(body, bg=PAGE)
        self.main.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self.views = {"sort": self._build_sort_view(), "cats": self._build_categories_view(),
                      "hist": self._build_history_view()}
        self.show_view("sort")

    def _build_sidebar(self) -> None:
        p, sb = self.px, self.sidebar
        # Room for 4 lines (so the mascot and buttons below stay put); it only grows for longer messages.
        self.bubble = tk.Frame(sb, bg=WHITE, highlightthickness=p(3), highlightbackground=INK,
                               height=self._bubble_height(4))
        bubble = self.bubble
        bubble.pack(fill="x", padx=p(20), pady=(p(22), 0))
        bubble.pack_propagate(False)
        self.mood_line = tk.Label(bubble, font=self.f_body, bg=WHITE, fg=INK, justify="left",
                                  anchor="w", wraplength=p(222))
        self.mood_line.pack(fill="both", expand=True, padx=p(10))
        tail = tk.Canvas(sb, width=p(26), height=p(13), bg=CREAM, highlightthickness=0)
        tail.pack()
        tail.create_polygon(0, 0, p(26), 0, p(13), p(13), fill=INK, outline="")
        tail.create_polygon(p(5), 0, p(21), 0, p(13), p(8), fill=WHITE, outline="")

        self.mascot = tk.Label(sb, bg=CREAM, bd=0, cursor="hand2")
        self.mascot.pack(pady=(p(6), p(4)))
        self.mascot.bind("<Enter>", lambda e: self._mascot(hover=True))
        self.mascot.bind("<Leave>", lambda e: self._mascot(hover=False))
        self.mascot.bind("<Button-1>", lambda e: self._poke())
        self.mood_title = tk.Label(sb, font=self.f_mood, bg=CREAM, fg=INK)
        self.mood_title.pack()

        nav = tk.Frame(sb, bg=CREAM)
        nav.pack(fill="x", padx=p(20), pady=(p(22), 0))
        self.nav_buttons: dict[str, PixelButton] = {}
        for key, label, icon in (("sort", "Sort", "nav/sort.png"),
                                 ("cats", "Categories", "nav/categories.png"),
                                 ("hist", "History", "nav/history.png")):
            b = PixelButton(nav, label, lambda k=key: self.show_view(k), app=self, bg=CREAM,
                            icon=self.sprites.get(icon, 1.25), width=p(240), anchor="w",
                            font=self.f_body_b, pady=7)
            b.pack(anchor="w", pady=(0, p(8)))
            self.nav_buttons[key] = b

    def show_view(self, key: str) -> None:
        self.view = key
        for k, frame in self.views.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for k, button in self.nav_buttons.items():
            button.set_face(YELLOW if k == key else WHITE)
        if key == "hist":
            self._refresh_history()

    def _heading(self, parent, text) -> tk.Frame:
        p = self.px
        head = tk.Frame(parent, bg=PAGE)
        head.pack(fill="x", padx=p(28), pady=(p(22), p(10)))
        tk.Label(head, text=text, font=self.f_title, bg=PAGE, fg=INK).pack(side="left")
        return head

    def _build_sort_view(self) -> tk.Frame:
        p = self.px
        view = tk.Frame(self.main, bg=PAGE)
        head = self._heading(view, "Your folders")
        self.add_btn = PixelButton(head, "+ Add folder", self._add_folder_menu, app=self, bg=PAGE)
        self.add_btn.pack(side="right")

        self.cards_frame = tk.Frame(view, bg=PAGE)
        self.cards_frame.pack(fill="x", padx=p(28))

        bar = tk.Frame(view, bg=PAGE)
        bar.pack(fill="x", padx=p(28), pady=(p(8), p(14)))
        self.preview_btn = PixelButton(bar, "Preview", self._preview, app=self, bg=PAGE, pady=9)
        self.preview_btn.pack(side="left")
        self.tidy_btn = SpriteButton(bar, "Tidy up!", self._sort_now, app=self, bg=PAGE)
        self.tidy_btn.pack(side="left", padx=p(14))
        self.undo_btn = PixelButton(bar, "Undo", self._undo_last, app=self, bg=PAGE, pady=9)
        self.undo_btn.pack(side="left")
        self.summary_var = tk.StringVar()
        tk.Label(bar, textvariable=self.summary_var, font=self.f_body, fg=MUTED, bg=PAGE).pack(
            side="left", padx=(p(16), 0))

        self._build_auto_bar(view)  # packed at the bottom before the panel takes the rest
        self.panel = tk.Frame(view, bg=PAGE)
        self.panel.pack(fill="both", expand=True, padx=p(28), pady=(0, p(14)))
        return view

    def _build_auto_bar(self, parent) -> None:
        p = self.px
        outer = tk.Frame(parent, bg=PAGE)
        outer.pack(side="bottom", fill="x", padx=p(28), pady=(0, p(20)))
        box = tk.Frame(outer, bg=CREAM, highlightthickness=p(3), highlightbackground=INK)
        box.pack(fill="x")
        row = tk.Frame(box, bg=CREAM)
        row.pack(fill="x", padx=p(14), pady=(p(10), p(2)))
        self.auto_var = tk.BooleanVar(value=self.settings.auto_sort)
        self.auto_switch = PixelSwitch(row, app=self, bg=CREAM, command=self._flip_auto,
                                       on=self.settings.auto_sort)
        self.auto_switch.pack(side="left")
        tk.Label(row, text="Keep these folders tidy automatically", font=self.f_body_b, bg=CREAM,
                 fg=INK).pack(side="left", padx=(p(10), p(18)))
        tk.Label(row, text="Check every", font=self.f_body, bg=CREAM, fg=INK).pack(side="left")
        self.interval_var = tk.StringVar(value=self._interval_label(self.settings.interval_seconds))
        interval = ttk.Combobox(row, textvariable=self.interval_var, values=[l for l, _ in INTERVALS],
                                state="readonly", width=11, font=self.f_body)
        interval.pack(side="left", padx=(p(8), 0))
        interval.bind("<<ComboboxSelected>>", self._on_interval_changed)
        self.auto_face = tk.Label(row, bg=CREAM, image=self.sprites.get("faces/smug.png", 2))
        self.auto_wait = tk.Label(box, bg=CREAM, fg=BLUE, font=self.f_small_b,  # its own line, so it always fits
                                  text="Waiting: auto-sort starts after your first Tidy up!")

        row2 = tk.Frame(box, bg=CREAM)
        row2.pack(fill="x", padx=p(14), pady=(p(4), p(12)))
        self.auto_row2 = row2
        exe_only = " (.exe only)"
        self.startup_var = tk.BooleanVar(value=startup.supported() and startup.is_enabled())
        start_cb = ttk.Checkbutton(row2, text="Start with Windows", variable=self.startup_var,
                                   command=self._toggle_startup, style="Cream.TCheckbutton")
        start_cb.pack(side="left")
        if not startup.supported():
            start_cb.configure(text=start_cb.cget("text") + exe_only)
            start_cb.state(["disabled"])
        self.tray_var = tk.BooleanVar(value=self.settings.close_to_tray)
        tray_cb = ttk.Checkbutton(row2, text="Keep running in the tray when closed",
                                  variable=self.tray_var, command=self._toggle_close_to_tray,
                                  style="Cream.TCheckbutton")
        tray_cb.pack(side="left", padx=(p(22), 0))
        if not self.tray:
            tray_cb.configure(text=tray_cb.cget("text") + exe_only)
            tray_cb.state(["disabled"])
        self.auto_state_var = tk.StringVar()

    def _build_categories_view(self) -> tk.Frame:
        p = self.px
        view = tk.Frame(self.main, bg=PAGE)
        head = self._heading(view, "Categories")
        PixelButton(head, "Reset", self._reset_categories, app=self, bg=PAGE).pack(side="right")
        self._wrap(tk.Label(view, text="Each file type becomes a folder. Files match by type: photo.jpg is a jpg. "
                                       "Click a file type to change it or its logo.", font=self.f_body, fg=MUTED,
                            bg=PAGE)).pack(fill="x", padx=p(28))

        holder, card = shadow_card(view, self, bg=PAGE, fill=CREAM)
        holder.pack(fill="x", padx=p(28), pady=(p(14), p(16)))
        inner = tk.Frame(card, bg=CREAM)
        inner.pack(fill="x", padx=p(14), pady=p(12))
        mode_row = tk.Frame(inner, bg=CREAM)
        mode_row.pack(fill="x")
        tk.Label(mode_row, text="Organize by", font=self.f_body_b, bg=CREAM, fg=INK).pack(side="left")
        self.mode_var = tk.StringVar(value=MODE_LABELS[self.settings.mode])
        mode_box = ttk.Combobox(mode_row, textvariable=self.mode_var, values=list(MODE_LABELS.values()),
                                state="readonly", width=36, font=self.f_body)
        mode_box.pack(side="left", padx=(p(12), 0))
        mode_box.bind("<<ComboboxSelected>>", self._on_options_changed)
        self.other_var = tk.BooleanVar(value=self.settings.other_folder)
        ttk.Checkbutton(inner, text='Put files of unknown types in an "Other" folder', variable=self.other_var,
                        command=self._on_options_changed, style="Cream.TCheckbutton").pack(anchor="w", pady=(p(10), 0))
        self.shortcut_var = tk.BooleanVar(value=self.settings.skip_shortcuts)
        ttk.Checkbutton(inner, text="Leave shortcuts (.lnk, .url) where they are", variable=self.shortcut_var,
                        command=self._on_options_changed, style="Cream.TCheckbutton").pack(anchor="w", pady=(p(4), 0))
        self.skipped_row = FlowFrame(inner, bg=CREAM, gap=self.px(14))  # filled by _refresh_skipped_row
        self.skipped_row.pack(fill="x", pady=(p(10), 0))

        self.cat_scroll = ScrollFrame(view, bg=PAGE)
        self.cat_scroll.pack(fill="both", expand=True, padx=(p(28), p(14)), pady=(0, p(18)))
        self._cat_cols = self._cat_columns_for(self.px(700))
        self.cat_scroll.canvas.bind("<Configure>", self._on_cat_resize, add="+")
        return view

    def _build_history_view(self) -> tk.Frame:
        p = self.px
        view = tk.Frame(self.main, bg=PAGE)
        self._heading(view, "History")
        tk.Label(view, text="Every tidy-up is listed here. Undo puts those files back exactly where they were.",
                 font=self.f_body, fg=MUTED, bg=PAGE, anchor="w").pack(fill="x", padx=p(28), pady=(0, p(14)))
        holder, card = shadow_card(view, self, bg=PAGE)
        holder.pack(fill="both", expand=True, padx=p(28), pady=(0, p(24)))
        self.hist_list = ScrollFrame(card, bg=WHITE)
        self.hist_list.pack(fill="both", expand=True)
        return view

    # ------------------------------------------------------------------ mascot

    def _mood(self) -> tuple[str, str, str]:
        known = {f: n for f, n in self.counts.items() if n is not None}
        total = sum(known.values())
        messy = [Path(f).name for f, n in known.items() if n]
        if self.busy:
            return "faces/front.png", "On it...", "Moving files into their folders."
        if not self.settings.folders:
            return "faces/front.png", "Hi there!", "Add a folder like Downloads and I’ll keep it tidy for you."
        if self.phase == "problem":
            return ("faces/sad.png", "Nearly there",
                    f"{plural(len(self.result[1]), 'file')} couldn’t move. They’re probably open in another program.")
        if self.phase == "preview":
            return ("faces/sad.png", "Here’s the plan",
                    "Every file gets a home. Nothing moves until you click Tidy up!, and you can undo it all.")
        if self.celebrating:
            return ("faces/happy_tongue.png", "All tidy!",
                    f"Moved {plural(self.result[0], 'file')}. Changed your mind? Undo puts them all back.")
        where = join_names(messy)
        if total <= HAPPY_UP_TO:
            if self.auto:
                return ("faces/smug.png", "I’ve got this",
                        "Auto-sort is on. New files get tidied after a minute, even while I’m in the tray.")
            if total == 0:
                return "faces/happy.png", "All tidy!", "Nothing loose in your folders. Nice."
            return ("faces/happy.png", "Nearly tidy",
                    f"Just {plural(total, 'loose file')} in {sentence(where)} Click Tidy up! to put "
                    f"{'it' if total == 1 else 'them'} away.")
        if total < MESSY_FROM:
            return ("faces/sad.png", "A bit messy",
                    f"{plural(total, 'loose file')} in {sentence(where)} Click Preview to see where they’d go.")
        return ("faces/dead.png", "Ugh, what a mess",
                f"{plural(total, 'loose file')} cluttering {sentence(where)} Click Preview to see where they’d go.")

    def _update_mood(self) -> None:
        art, title, line = self._mood()
        if self.mascot_hover:
            art = "faces/surprised.png"
        if not self.animating:  # the animation draws the buddy itself while it plays
            self.mascot.configure(image=self.sprites.get(art, 8))
            self.mascot.image_name = art  # for tests
        self.mood_title.configure(text=title)
        self.mood_line.configure(text=line)
        lines = max(4, wrapped_lines(line, self.f_body, self.px(222)))
        if int(self.bubble.cget("height")) != self._bubble_height(lines):
            self.bubble.configure(height=self._bubble_height(lines))
        total = sum(n for n in self.counts.values() if n)
        hints = {
            "preview": "Nothing moves until you click Tidy up!",
            "done": "Undo puts everything back.",
            "problem": "Close those files, then click Tidy up! again.",
        }
        self.summary_var.set(hints.get(self.phase) or
                             (f"{plural(total, 'loose file')} to tidy" if total else ""))
        self.preview_btn.set_enabled(not self.busy and bool(self.settings.folders))
        self.tidy_btn.set_enabled(not self.busy)
        self.undo_btn.set_enabled(not self.busy and self.history.latest_undoable() is not None)

    def _mascot(self, hover: bool) -> None:
        self.mascot_hover = hover
        self._update_mood()

    def _poke(self) -> None:
        """Clicking the buddy plays the sorting animation once."""
        if not self.busy:
            self._play_animation_once()

    # ------------------------------------------------------------------ sorting animation

    def _sorting_frames(self) -> list[tuple[str, int]]:
        """[(art, milliseconds)] from assets/sorting/Sorting_1.png, Sorting_2.png... and timings.txt."""
        if self._anim_frames is None:
            folder = ASSETS / "sorting"
            files = sorted(folder.glob("Sorting_*.png"),
                           key=lambda f: int(re.sub(r"\D", "", f.stem) or 0))
            try:
                lines = (folder / "timings.txt").read_text(encoding="utf-8-sig").splitlines()
                timings = [int(n) for n in re.findall(r"\d+", "\n".join(
                    l for l in lines if not l.strip().startswith("#")))]
            except (OSError, ValueError):
                timings = []
            self._anim_frames = [
                (f"sorting/{f.name}", timings[i] if i < len(timings) else (300 if i == len(files) - 1 else 120))
                for i, f in enumerate(files)]
            for art, _ in self._anim_frames:  # load them all now so no frame stutters mid-animation
                self.sprites.get(art, 8)
        return self._anim_frames

    def _start_animation(self) -> None:
        if self.animating or not self._sorting_frames():
            return
        self.animating, self._anim_index, self._anim_stop, self._anim_finish = True, 0, False, None
        self._anim_step()

    def _anim_step(self) -> None:
        if not self.animating:
            return
        frames = self._sorting_frames()
        art, ms = frames[self._anim_index]
        self.mascot.configure(image=self.sprites.get(art, 8))
        self.mascot.image_name = art
        self._anim_index += 1
        if self._anim_index >= len(frames):
            self._anim_index = 0
            if self._anim_stop:  # a full loop is done and so is the work
                self.after(ms, self._end_animation)
                return
        self.after(ms, self._anim_step)

    def _end_animation(self) -> None:
        self.animating = False
        callback, self._anim_finish = self._anim_finish, None
        self._update_mood()
        if callback:
            callback()

    def _when_animation_ends(self, callback) -> None:
        """Run `callback` once the current loop finishes (right away if nothing is playing)."""
        if self.animating:
            self._anim_finish, self._anim_stop = callback, True
        else:
            callback()

    def _play_animation_once(self) -> None:
        if not self.animating:
            self._start_animation()
            self._when_animation_ends(lambda: None)

    def _celebrate(self) -> None:
        self.celebrating = True
        self._update_mood()
        self._sparkle()
        self.after(3500, self._end_celebration)

    def _end_celebration(self) -> None:
        self.celebrating = False
        self._update_mood()

    def _sparkle(self) -> None:
        p = self.px
        frames = [self.sprites.get(f"sparkle/{i}.png", 4) for i in (1, 2, 3)]
        self.update_idletasks()
        mx, my = self.mascot.winfo_x(), self.mascot.winfo_y()
        mw, mh = self.mascot.winfo_width(), self.mascot.winfo_height()
        spots = [(mx - p(42), my + p(30)), (mx + mw + p(8), my + p(6)), (mx + mw + p(4), my + mh - p(50))]
        labels = [tk.Label(self.sidebar, bg=CREAM, bd=0) for _ in spots]
        seq = [0, 1, 2, 1, 0, 1, 2, 1, 0]

        def step(i: int) -> None:
            if i > len(seq) + 2:
                for label in labels:
                    label.destroy()
                return
            for k, (label, (x, y)) in enumerate(zip(labels, spots)):
                j = i - k
                if 0 <= j < len(seq):
                    label.configure(image=frames[seq[j]])
                    label.place(x=x, y=y)
                else:
                    label.place_forget()
            self.after(140, lambda: step(i + 1))
        step(0)

    # ------------------------------------------------------------------ scanning & folder cards

    def _scan(self) -> None:
        counts: dict[str, int | None] = {}
        for folder in self.settings.folders:
            if engine.folder_problem(folder):
                counts[folder] = None
            else:
                counts[folder] = len(engine.plan_sort(folder, self.settings))
        self.counts = counts

    def _periodic(self) -> None:
        """Every few seconds, re-count loose files so the faces stay current."""
        try:
            if self.state() != "withdrawn" and not self.busy and self.phase != "preview":
                before = dict(self.counts)
                self._scan()
                if self.counts != before:
                    if self.phase in ("done", "problem") and any(self.counts.values()):
                        self.phase = "idle"
                        self._show_panel()
                    self._update_folder_cards()
                    self._update_mood()
        finally:
            self.after(8000, self._periodic)

    def _rebuild_folder_cards(self) -> None:
        p = self.px
        for widget in self.cards_frame.winfo_children():
            widget.destroy()
        self.card_widgets = {}
        folders = self.settings.folders
        if not folders:
            holder, card = shadow_card(self.cards_frame, self, bg=PAGE, fill=CREAM)
            holder.pack(fill="x", pady=(0, p(10)))
            inner = tk.Frame(card, bg=CREAM)
            inner.pack(fill="x", padx=p(16), pady=p(14))
            tk.Label(inner, image=self.sprites.get("faces/front.png", 3), bg=CREAM).pack(side="left")
            text = tk.Frame(inner, bg=CREAM)
            text.pack(side="left", fill="x", expand=True, padx=(p(16), 0))
            tk.Label(text, text="Which folders should I keep tidy?", font=self.f_name, bg=CREAM,
                     fg=INK, anchor="w").pack(anchor="w")
            quick = tk.Frame(text, bg=CREAM)
            quick.pack(anchor="w", pady=(p(8), 0))
            for name in ("Downloads", "Desktop", "Documents"):
                PixelButton(quick, name, lambda n=name: self._add_folder(known_folder(n)), app=self,
                            bg=CREAM).pack(side="left", padx=(0, p(10)))
            PixelButton(quick, "Choose...", self._browse_folder, app=self, bg=CREAM).pack(side="left")
            return
        cols = 2  # two per row leaves room for long folder names and paths
        for c in range(cols):
            self.cards_frame.columnconfigure(c, weight=1, uniform="cards")
        for i, folder in enumerate(folders):
            holder, card = shadow_card(self.cards_frame, self, bg=PAGE)
            holder.grid(row=i // cols, column=i % cols, sticky="nsew",
                        padx=(0, p(14) if i % cols < cols - 1 else 0), pady=(0, p(14)))
            inner = tk.Frame(card, bg=WHITE)
            inner.pack(fill="both", expand=True, padx=p(12), pady=p(10))
            face = tk.Label(inner, bg=WHITE)
            face.pack(side="left")
            info = tk.Frame(inner, bg=WHITE)
            info.pack(side="left", fill="x", expand=True, padx=(p(12), 0))
            name = tk.Label(info, font=self.f_name, bg=WHITE, fg=INK, anchor="w", width=1)
            name.pack(fill="x")
            self._fit_on_resize(name, Path(folder).name or folder, self.f_name)
            count = tk.Label(info, font=self.f_body_b, bg=WHITE, fg=INK, anchor="w")
            count.pack(anchor="w")
            where = tk.Label(info, font=self.f_small, bg=WHITE, fg=MUTED, anchor="w", width=1)
            where.pack(fill="x")
            self._fit_on_resize(where, folder, self.f_small, side="start")
            links = tk.Frame(info, bg=WHITE)
            links.pack(anchor="w", pady=(p(2), 0))
            link(links, "Open", lambda f=folder: self._open_folder(f), app=self, bg=WHITE).pack(side="left")
            tk.Label(links, text=" · ", font=self.f_small, bg=WHITE, fg=MUTED).pack(side="left")
            link(links, "Remove", lambda f=folder: self._remove_folder(f), app=self, bg=WHITE).pack(side="left")
            self.card_widgets[folder] = (face, count)
        self._update_folder_cards()

    def _bubble_height(self, lines: int) -> int:
        return self.f_body.metrics("linespace") * lines + self.px(16) + 2 * self.px(3)

    @staticmethod
    def _wrap(label: tk.Label) -> tk.Label:
        """Let the label's text wrap to whatever width it gets, so nothing runs off the edge."""
        label.configure(width=1, justify="left", anchor="w")
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(30, e.width - 4)), add="+")
        return label

    @staticmethod
    def _fit_on_resize(label: tk.Label, text: str, font: tkfont.Font, side: str = "end") -> None:
        """Show as much of `text` as fits the label's width, ending in "…" if it's cut (display only)."""
        label.configure(text=text)
        label.bind("<Configure>", lambda e: label.configure(text=fit_text(text, font, e.width - 4, side)))

    def _update_folder_cards(self) -> None:
        for folder, (face, count) in self.card_widgets.items():
            n = self.counts.get(folder)
            if n is None:
                face.configure(image=self.sprites.get("faces/front.png", 3))
                count.configure(text="Can't find this folder", fg=MUTED)
            else:
                face.configure(image=self.sprites.get(face_for(n), 3))
                count.configure(text="All tidy" if n == 0 else plural(n, "loose file"), fg=INK)

    # ------------------------------------------------------------------ the panel under the buttons

    def _clear_panel(self) -> None:
        for widget in self.panel.winfo_children():
            widget.destroy()

    def _show_panel(self) -> None:
        self._clear_panel()
        if self.phase == "preview":
            self._panel_plan()
        elif self.phase in ("done", "problem"):
            self._panel_result()
        else:
            self._panel_idle()

    def _hint_box(self, art: str, text: str) -> None:
        p = self.px
        box = tk.Frame(self.panel, bg=HINT_BG, highlightthickness=p(3), highlightbackground=TAB)
        box.pack(fill="x")
        inner = tk.Frame(box, bg=HINT_BG)
        inner.pack(fill="x", padx=p(16), pady=p(12))
        tk.Label(inner, image=self.sprites.get(art, 2), bg=HINT_BG).pack(side="left")
        self._wrap(tk.Label(inner, text=text, font=self.f_body, bg=HINT_BG, fg=INK)).pack(
            side="left", padx=(p(14), 0), fill="x", expand=True)

    def _panel_idle(self) -> None:
        if not self.settings.folders:
            return
        if any(self.counts.values()):
            self._hint_box("faces/front.png", "Click Preview to see exactly where each file would go. "
                                              "Nothing moves until you click Tidy up!")
        else:
            self._hint_box("faces/happy.png", "Nothing to tidy right now. New files in your folders will "
                                              "show up here.")

    def _panel_plan(self) -> None:
        p = self.px
        skip = set(self.settings.skipped_groups)
        groups: dict[tuple[str, str], list[tuple[str, engine.Move]]] = defaultdict(list)
        for folder, moves in self.plans.items():
            for m in moves:
                groups[(m.rule, m.category)].append((folder, m))

        def excluded(items) -> bool:
            return engine.is_excluded(items[0][1], skip)

        moving = [fm for v in groups.values() if not excluded(v) for fm in v]
        targets = {str(Path(m.dst).parent).lower() if m.rule else dest_label(m, f).lower() for f, m in moving}
        n_excluded = sum(len(v) for v in groups.values()) - len(moving)
        head = tk.Frame(self.panel, bg=PAGE)
        head.pack(fill="x", pady=(0, p(8)))
        tk.Label(head, text=f"The plan: {plural(len(moving), 'file')} into {plural(len(targets), 'folder')}",
                 font=self.f_h2, bg=PAGE, fg=INK).pack(side="left")
        if n_excluded:
            tk.Label(head, text=f"   ({plural(n_excluded, 'file')} excluded)", font=self.f_body, bg=PAGE,
                     fg=MUTED).pack(side="left", pady=(p(3), 0))
        holder, card = shadow_card(self.panel, self, bg=PAGE)
        holder.pack(fill="both", expand=True)
        scroller = ScrollFrame(card, bg=WHITE)
        scroller.pack(fill="both", expand=True)

        # All courses share one "Courses" row and all code words one "Code words" row (each with a
        # dropdown); then file types, biggest first; excluded groups at the end.
        bundles = {kind: {k: v for k, v in groups.items() if k[0] == kind} for kind in BUNDLES}
        others = {k: v for k, v in groups.items() if k[0] not in BUNDLES}
        moving_bundles = [kind for kind, g in bundles.items() if any(not excluded(v) for v in g.values())]
        entries: list[tuple[str, object]] = [("bundle", kind) for kind in moving_bundles]
        entries += [("group", kv) for kv in sorted(
            ((k, v) for k, v in others.items() if not excluded(v)),
            key=lambda kv: (kv[0][0] == "", -len(kv[1]), kv[0][1]))]
        entries += [("bundle", kind) for kind, g in bundles.items() if g and kind not in moving_bundles]
        entries += [("group", kv) for kv in sorted(
            ((k, v) for k, v in others.items() if excluded(v)), key=lambda kv: kv[0][1].lower())]
        for i, (kind, payload) in enumerate(entries):
            if kind == "bundle":
                self._plan_bundle_row(scroller.inner, payload, bundles[payload], skip, first=i == 0)
            else:
                (rule, cat), items = payload
                self._plan_group_row(scroller.inner, rule, cat, items, excluded(items), first=i == 0)

    def _plan_group_row(self, parent, rule: str, cat: str, items, is_excluded: bool, *, first: bool = False,
                        indent: int = 0, child: bool = False, locked: bool = False) -> None:
        """One group in the plan. `child`: a course or code word inside the Courses / Code words
        dropdown. `locked`: excluded because all of them are, so it has no link of its own."""
        p = self.px
        bg = SKIPPED_BG if is_excluded else WHITE
        key = engine.group_key(items[0][1])
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x")
        if not first:
            tk.Frame(row, bg=LINE, height=p(1 if child else 2)).pack(fill="x")
        inner = tk.Frame(row, bg=bg)
        inner.pack(fill="x", padx=(p(12) + indent, p(12)), pady=p(6 if child else 8))
        icon = "" if rule in BUNDLES else cat  # a course / code word goes to its own folder: the plain folder logo
        tk.Label(inner, image=self.category_sprite(icon, 1.5 if child else 2), bg=bg).pack(side="left", anchor="n")
        if is_excluded:
            tk.Label(inner, text="Left where it is", font=self.f_small_b, bg=bg, fg=MUTED, padx=p(6),
                     pady=p(2), highlightthickness=p(2), highlightbackground=LINE).pack(side="right", anchor="n")
        else:
            dests = sorted({dest_label(m, f) for f, m in items})
            chip = "→ " + ", ".join(dests[:2]) + (", ..." if len(dests) > 2 else "") + "\\"
            chip_label = tk.Label(inner, text=chip, font=self.f_small_b, bg=CHIP_BG, fg=CHIP_FG, padx=p(6),
                                  pady=p(2), highlightthickness=p(2), highlightbackground=BLUE)
            chip_label.pack(side="right", anchor="n")
            folders = sorted({str(dest_folder(m)) for _, m in items}, key=str.lower)
            new = [d for d in folders if not Path(d).exists()]
            Tooltip(chip_label, "Files go to:\n" + "\n".join(folders[:4]) +
                    (f"\n...and {len(folders) - 4} more" if len(folders) > 4 else "") +
                    ("\n\n(new folder: it'll be made when you click Tidy up!)" if new else ""), app=self)
            if new:  # this tidy-up will create the folder: show it, say so on hover, click to choose where
                if not rule and self.settings.mode != "month":
                    pick = lambda c=cat: self._choose_location(c)  # noqa: E731
                elif rule == "word":
                    pick = lambda k=key: self._choose_word_location(k)  # noqa: E731
                else:
                    pick = None
                self._new_folder_badge(inner, bg, new, pick, "Click to choose where to make it.")
        text = tk.Frame(inner, bg=bg)
        text.pack(side="left", fill="x", expand=True, padx=p(12))
        self._wrap(tk.Label(text, text=f"{cat}  ·  {plural(len(items), 'file')}" +
                            ("  ·  excluded" if is_excluded else ""), font=self.f_body_b, bg=bg,
                            fg=MUTED if is_excluded else INK)).pack(fill="x")
        names = [Path(m.src).name for _, m in items]
        shown = ", ".join(names[:3]) + (f"  + {len(names) - 3} more" if len(names) > 3 else "")
        names_label = self._wrap(tk.Label(text, text=shown, font=self.f_small, bg=bg, fg=MUTED))
        names_label.pack(fill="x")
        links = tk.Frame(text, bg=bg)
        links.pack(anchor="w")
        if len(names) > 3:
            everything = ", ".join(names)
            more = link(links, "Show all", lambda: None, app=self, bg=bg)

            def flip(_event=None, label=names_label, toggle=more, short=shown, full=everything):
                expanded = toggle.cget("text") == "Show less"
                label.configure(text=short if expanded else full)
                toggle.configure(text="Show all" if expanded else "Show less")
            more.bind("<Button-1>", flip)
            more.pack(side="left")
            tk.Label(links, text=" · ", font=self.f_small, bg=bg, fg=MUTED).pack(side="left")
        if locked:
            tk.Label(links, text=f"excluded with all {BUNDLES[rule]['title'].lower()}", font=self.f_small, bg=bg,
                     fg=MUTED).pack(side="left")
        elif is_excluded:
            link(links, "Include again", lambda k=key: self._include_group(k), app=self, bg=bg).pack(side="left")
        else:
            link(links, "Exclude", lambda k=key: self._skip_group(k), app=self, bg=bg).pack(side="left")
        if not rule and cat in self.settings.category_locations and self.settings.mode != "month":
            tk.Label(links, text=" · ", font=self.f_small, bg=bg, fg=MUTED).pack(side="left")
            link(links, "Reset location", lambda c=cat: self._reset_location(c), app=self, bg=bg).pack(side="left")

    def _new_folder_badge(self, parent, bg: str, new: list[str], on_click=None, hint: str = "") -> None:
        """The folder-with-a-plus symbol: this tidy-up will create these folders. Says so on hover;
        `on_click` (if given) lets you choose where."""
        badge = tk.Label(parent, image=self.sprites.get("badges/new_folder.png", 1.5), bg=bg,
                         cursor="hand2" if on_click else "question_arrow")
        badge.pack(side="right", anchor="n", padx=(0, self.px(6)))
        badge.image_name = "new_folder"  # for tests
        badge.on_click = on_click        # for tests
        Tooltip(badge, ("New folder: Tidy Folders will create\n" if len(new) == 1 else
                        "New folders: Tidy Folders will create\n") + "\n".join(new[:4]) +
                (f"\n...and {len(new) - 4} more" if len(new) > 4 else "") + "\nwhen you click Tidy up!" +
                (f"\n\n{hint}" if on_click and hint else ""), app=self)
        if on_click:
            badge.bind("<Button-1>", lambda e: self.after_idle(on_click), add="+")

    def _plan_bundle_row(self, parent, kind: str, groups, skip: set[str], *, first: bool) -> None:
        """The "Courses" or "Code words" row: every course / code word together, with
        Exclude all / Include all and a dropdown listing each one."""
        p = self.px
        b = BUNDLES[kind]
        all_out = b["all"] in skip
        out = {k: engine.is_excluded(v[0][1], skip) for k, v in groups.items()}
        n_groups, n_out = len(groups), sum(out.values())
        fully_out = n_out == n_groups
        files_total = sum(len(v) for v in groups.values())
        files_moving = sum(len(v) for k, v in groups.items() if not out[k])
        bg = SKIPPED_BG if fully_out else WHITE
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x")
        if not first:
            tk.Frame(row, bg=LINE, height=p(2)).pack(fill="x")
        inner = tk.Frame(row, bg=bg)
        inner.pack(fill="x", padx=p(12), pady=p(8))
        tk.Label(inner, image=self.category_sprite(b["icon"]), bg=bg).pack(side="left", anchor="n")
        if fully_out:
            tk.Label(inner, text="Left where they are", font=self.f_small_b, bg=bg, fg=MUTED, padx=p(6),
                     pady=p(2), highlightthickness=p(2), highlightbackground=LINE).pack(side="right", anchor="n")
        else:
            where = sorted({str(dest_folder(m)) for k, v in groups.items() if not out[k] for _, m in v},
                           key=str.lower)
            chip = tk.Label(inner, text=f"→ {plural(len(where), b['dest_noun'])}", font=self.f_small_b,
                            bg=CHIP_BG, fg=CHIP_FG, padx=p(6), pady=p(2), highlightthickness=p(2),
                            highlightbackground=BLUE)
            chip.pack(side="right", anchor="n")
            Tooltip(chip, b["tip"] + "\n" + "\n".join(where[:6]) +
                    (f"\n...and {len(where) - 6} more" if len(where) > 6 else ""), app=self)
            new = [d for d in where if not Path(d).exists()]
            if new:  # click: open the list, where each new folder has its own symbol to choose where it goes
                self._new_folder_badge(inner, bg, new, lambda: self.expanded[kind] or flip(),
                                       f"Click to see each {b['noun']}, then click its symbol to choose where "
                                       "its folder goes.")
        text = tk.Frame(inner, bg=bg)
        text.pack(side="left", fill="x", expand=True, padx=p(12))
        status = "  ·  excluded" if fully_out else (f"  ·  {n_out} excluded" if n_out else "")
        self._wrap(tk.Label(text, text=f"{b['title']}  ·  {plural(files_moving if not fully_out else files_total, 'file')}"
                                       f"  ·  {plural(n_groups, b['noun'])}{status}",
                            font=self.f_body_b, bg=bg, fg=MUTED if fully_out else INK)).pack(fill="x")
        names = sorted((k[1] for k in groups), key=str.lower)
        self._wrap(tk.Label(text, text=", ".join(names), font=self.f_small, bg=bg, fg=MUTED)).pack(fill="x")
        links = tk.Frame(text, bg=bg)
        links.pack(anchor="w")
        title = b["title"].lower()

        def toggle_text() -> str:
            return f"Hide {title} ▴" if self.expanded[kind] else f"Show {title} ▾"
        toggle = link(links, toggle_text(), lambda: None, app=self, bg=bg)
        toggle.pack(side="left")
        if n_out:
            tk.Label(links, text=" · ", font=self.f_small, bg=bg, fg=MUTED).pack(side="left")
            link(links, f"Include all {title}", lambda: self._include_all(kind), app=self, bg=bg).pack(side="left")
        if not fully_out:
            tk.Label(links, text=" · ", font=self.f_small, bg=bg, fg=MUTED).pack(side="left")
            link(links, f"Exclude all {title}", lambda: self._exclude_all(kind), app=self, bg=bg).pack(side="left")

        children = tk.Frame(row, bg=WHITE)
        for k, v in sorted(groups.items(), key=lambda kv: (out[kv[0]], -len(kv[1]), kv[0][1].lower())):
            self._plan_group_row(children, kind, k[1], v, out[k], indent=p(48), child=True, locked=all_out)
        if self.expanded[kind]:
            children.pack(fill="x")

        def flip(_event=None):
            self.expanded[kind] = not self.expanded[kind]
            if self.expanded[kind]:
                children.pack(fill="x")
            else:
                children.pack_forget()
            toggle.configure(text=toggle_text())
        toggle.bind("<Button-1>", flip)

    # ------------------------------------------------------------------ skipping groups

    @staticmethod
    def _group_name(key: str) -> str:
        kind, _, name = key.partition(":")
        if name == "*" and kind in BUNDLES:
            return "All " + BUNDLES[kind]["title"].lower()
        if kind == "course":
            return re.sub(r"^([A-Z]+)(\d)", r"\1 \2", name)
        return f'"{name}"' if kind == "word" else name

    def _skip_group(self, key: str) -> None:
        if key not in self.settings.skipped_groups:
            self.settings.skipped_groups.append(key)
            self._save()
        self._after_plan_rules_changed(f"Excluded {self._group_name(key)}: those files will be left where they are.")

    def _include_group(self, key: str) -> None:
        if key in self.settings.skipped_groups:
            self.settings.skipped_groups.remove(key)
            self._save()
        self._after_plan_rules_changed(f"{self._group_name(key)} will be sorted again.")

    # ------------------------------------------------------------------ where new folders go

    def _ask_place(self, name: str, start: str | Path | None) -> Path | None:
        """Ask where the `name` folder should be made. Returns the folder to make it in, or None.
        Picking a folder that's already called `name` means "use that one"."""
        start = Path(start) if start and Path(start).is_dir() else (
            Path(self.settings.folders[0]) if self.settings.folders else Path.home())
        path = filedialog.askdirectory(parent=self, mustexist=True, initialdir=str(start),
                                       title=f'Where should the "{name}" folder go?')
        if not path:
            return None
        place = Path(path)
        if place.name.lower() == name.lower():
            place = place.parent
        problem = engine.target_problem(place / name)
        if problem:
            messagebox.showwarning(APP_NAME, f"{place / name}\n\n{problem}", parent=self)
            return None
        return place

    def _choose_location(self, category: str) -> None:
        """Make a file type's folder somewhere else, e.g. Documents\\3D Printing, instead of
        inside each folder being tidied."""
        place = self._ask_place(category, self.settings.category_locations.get(category))
        if place is None:
            return
        home = [Path(f) for f in self.settings.folders]
        if len(home) == 1 and engine.same_folder(place, home[0]):  # that's where it goes anyway
            self.settings.category_locations.pop(category, None)
        else:
            self.settings.category_locations[category] = str(place)
        self._save()
        self._after_plan_rules_changed(f"{category} files will go to {place / category}.")

    def _reset_location(self, category: str) -> None:
        if self.settings.category_locations.pop(category, None):
            self._save()
        self._after_plan_rules_changed(f"{category} files will go into a {category} folder inside "
                                       "each folder you tidy again.")

    def _choose_word_location(self, key: str) -> None:
        """Move a code word's (not yet made) folder somewhere else."""
        rule = next((r for r in self.settings.keyword_rules
                     if "word:" + "".join(c for c in r["word"].lower() if c.isalnum()) == key), None)
        if rule is None:
            return
        old = Path(rule["folder"])
        place = self._ask_place(old.name, old.parent)
        if place is None:
            return
        target = place / old.name
        if any(engine.same_folder(target, f) for f in self.settings.folders):
            messagebox.showwarning(APP_NAME, f"{target}\n\nThat's one of the folders being tidied. "
                                             "Choose somewhere else.", parent=self)
            return
        rule["folder"] = str(target)
        self._save()
        self._after_plan_rules_changed(f'Files with "{rule["word"]}" in their name will go to {target}.')

    def _exclude_all(self, kind: str) -> None:
        """Leave every course (or code word) alone, including ones added later."""
        b = BUNDLES[kind]
        if b["all"] not in self.settings.skipped_groups:
            self.settings.skipped_groups.append(b["all"])
            self._save()
        self._after_plan_rules_changed(f"Excluded all {b['title'].lower()}: their files will be left where they are.")

    def _include_all(self, kind: str) -> None:
        """Sort every course (or code word) again, including ones that were excluded one by one."""
        self.settings.skipped_groups = [k for k in self.settings.skipped_groups if not k.startswith(kind + ":")]
        self._save()
        self._after_plan_rules_changed(f"All {BUNDLES[kind]['title'].lower()} will be sorted again.")

    def _after_plan_rules_changed(self, message: str) -> None:
        if self.phase == "preview" and not self.busy:
            self._preview()
        else:
            self._refresh_everything()
        self._refresh_categories()
        self.status_var.set(message)

    def _panel_result(self) -> None:
        p = self.px
        moved, errors = self.result
        bg = WHITE if errors else CREAM
        holder, card = shadow_card(self.panel, self, bg=PAGE, fill=bg)
        holder.pack(fill="x")
        inner = tk.Frame(card, bg=bg)
        inner.pack(fill="x", padx=p(16), pady=p(14))
        art = "faces/sad.png" if errors else ("faces/smug.png" if self.auto else "faces/happy.png")
        tk.Label(inner, image=self.sprites.get(art, 3), bg=bg).pack(side="left", anchor="n")
        text = tk.Frame(inner, bg=bg)
        text.pack(side="left", fill="x", expand=True, padx=(p(16), 0))
        if errors:
            title = f"{plural(len(errors), 'file')} stayed put"
            line = f"Moved {plural(moved, 'file')}, but these couldn’t move:"
        else:
            title = "All tidy!"
            line = f"Moved {plural(moved, 'file')} into folders. Changed your mind? Undo puts every one back."
        tk.Label(text, text=title, font=self.f_h2, bg=bg, fg=INK, anchor="w").pack(fill="x")
        self._wrap(tk.Label(text, text=line, font=self.f_body, bg=bg, fg=INK)).pack(fill="x")
        for err in errors[:5]:
            self._wrap(tk.Label(text, text="•  " + err, font=self.f_small, bg=bg, fg=MUTED)).pack(fill="x")
        if len(errors) > 5:
            tk.Label(text, text=f"...and {len(errors) - 5} more.", font=self.f_small, bg=bg, fg=MUTED,
                     anchor="w").pack(fill="x")

    # ------------------------------------------------------------------ infrastructure

    def _save(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as e:
            self.status_var.set(f"Couldn't save settings: {e}")
        if self.auto:
            self.auto.update_settings(self.settings)

    def _drain_events(self) -> None:
        """Run callbacks that background threads queued for the UI thread."""
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _run_in_background(self, work, on_done, message: str, animate: bool = False) -> None:
        self._set_busy(True, message)
        if animate:
            self._start_animation()

        def runner():
            try:
                result = work()
            except Exception as err:  # surface anything unexpected instead of dying silently
                def fail(err=err):
                    self.animating = False
                    self._set_busy(False)
                    messagebox.showerror(APP_NAME, f"Something went wrong:\n\n{err}", parent=self)
                self.events.put(fail)
                return

            def finish():
                def done():
                    self._set_busy(False)
                    on_done(result)
                self._when_animation_ends(done)  # let the animation finish its loop first
            self.events.put(finish)

        threading.Thread(target=runner, daemon=True).start()

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.busy = busy
        self.configure(cursor="watch" if busy else "")
        if message:
            self.status_var.set(message)
        self._update_mood()

    def _show_problems(self, title: str, problems: list[str]) -> None:
        shown = problems[:15]
        extra = f"\n...and {len(problems) - 15} more." if len(problems) > 15 else ""
        messagebox.showwarning(APP_NAME, title + "\n\n" + "\n".join(f"- {p}" for p in shown) + extra,
                               parent=self)

    def _interval_label(self, seconds: int) -> str:
        return next((label for label, s in INTERVALS if s == seconds), f"{seconds} seconds")

    def _on_wheel(self, e) -> None:
        widget = self.winfo_containing(e.x_root, e.y_root)
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                widget.scroll(-2 if e.delta > 0 else 2)
                return
            widget = widget.master

    def _refresh_everything(self) -> None:
        self._scan()
        self._update_folder_cards()
        self._show_panel()
        self._update_mood()

    # ------------------------------------------------------------------ folders

    def _add_folder_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, font=self.f_body)
        current = {Path(f).resolve() for f in self.settings.folders}
        for name in ("Downloads", "Desktop", "Documents"):
            path = known_folder(name)
            unavailable = not path.exists() or path.resolve() in current
            menu.add_command(label=name, command=lambda f=path: self._add_folder(f),
                             state="disabled" if unavailable else "normal")
        menu.add_separator()
        menu.add_command(label="Choose a folder...", command=self._browse_folder)
        x = self.add_btn.winfo_rootx()
        y = self.add_btn.winfo_rooty() + self.add_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _browse_folder(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Choose a folder to tidy", mustexist=True)
        if path:
            self._add_folder(Path(path))

    def _add_folder(self, path: Path) -> None:
        path_str = str(Path(path))
        problem = engine.folder_problem(path_str)
        if problem:
            messagebox.showwarning(APP_NAME, f"{path_str}\n\n{problem}", parent=self)
            return
        resolved = Path(path_str).resolve()
        if any(Path(f).resolve() == resolved for f in self.settings.folders):
            self.status_var.set(f"{path_str} is already in the list.")
            return
        if self.auto and not messagebox.askyesno(
                APP_NAME, "Automatic sorting is on, so files in this folder will start being "
                          f"sorted right away.\n\n{path_str}\n\nAdd it?", parent=self):
            return
        self.settings.folders.append(path_str)
        self._save()
        self.phase = "idle"
        self._scan()
        self._rebuild_folder_cards()
        self._show_panel()
        self._update_mood()
        self.status_var.set(f"Added {Path(path_str).name or path_str}. Click Preview to see what would move.")

    def _remove_folder(self, folder: str) -> None:
        if folder in self.settings.folders:
            self.settings.folders.remove(folder)
            self._save()
        self.phase = "idle"
        self._scan()
        self._rebuild_folder_cards()
        self._show_panel()
        self._update_mood()
        self.status_var.set(f"Removed {Path(folder).name}. Files already sorted stay where they are.")

    def _open_folder(self, folder: str) -> None:
        if Path(folder).is_dir() and hasattr(os, "startfile"):
            os.startfile(folder)

    # ------------------------------------------------------------------ preview & sort

    def _plan_all(self, quiet: bool = False, include_skipped: bool = False) -> dict[str, list[engine.Move]]:
        plans: dict[str, list[engine.Move]] = {}
        skipped = []
        for folder in self.settings.folders:
            problem = engine.folder_problem(folder)
            if problem:
                skipped.append(f"{folder}: {problem}")
                continue
            moves = engine.plan_sort(folder, self.settings, include_skipped=include_skipped)
            if moves:
                plans[folder] = moves
        if skipped and not quiet:
            self._show_problems("These folders were skipped:", skipped)
        return plans

    def _preview(self) -> dict[str, list[engine.Move]]:
        if self.busy:
            return {}
        if not self.settings.folders:
            self._add_folder_menu()
            return {}
        self.plans = self._plan_all(quiet=True, include_skipped=True)  # skipped groups are shown, greyed
        skip = set(self.settings.skipped_groups)
        self.counts = {f: (None if engine.folder_problem(f) else
                           sum(1 for m in self.plans.get(f, []) if not engine.is_excluded(m, skip)))
                       for f in self.settings.folders}
        has_moves = any(self.plans.values())
        self.phase = "preview" if has_moves else "idle"
        self.show_view("sort")
        self._update_folder_cards()
        self._show_panel()
        self._update_mood()
        self.status_var.set("Preview only. Nothing has moved yet." if has_moves
                            else "Nothing to sort. Your folders are already tidy.")
        return self.plans

    def _sort_now(self) -> None:
        if self.busy:
            return
        if not self.settings.folders:
            self._add_folder_menu()
            return
        previewed = self.phase == "preview"
        plans = self._plan_all(quiet=True)  # skipped groups left out
        total = sum(len(m) for m in plans.values())
        if total == 0:
            self.phase = "idle"
            self._arm_auto()  # a Tidy up! with nothing to move still counts as the first one
            self._refresh_everything()
            self.status_var.set("Nothing to sort. Your folders are already tidy.")
            return
        if not previewed and not messagebox.askyesno(
                APP_NAME, f"Move {plural(total, 'file')} into folders?\n\nNothing is deleted, and you can "
                          "undo this afterwards. (Click Preview first to see where each file goes.)",
                parent=self):
            return
        batch = uuid.uuid4().hex[:12]

        def work():
            return [engine.apply_moves(moves, folder, "manual", self.history, batch)
                    for folder, moves in plans.items()]
        self._run_in_background(work, self._after_sort, f"Sorting {plural(total, 'file')}...", animate=True)

    def _after_sort(self, results, quiet: bool = False) -> None:
        moved = sum(len(run["moves"]) for run, _ in results)
        errors = [e for _, errs in results for e in errs]
        self.result = (moved, errors)
        self.phase = "problem" if errors else "done"
        self.plans = {}
        self._arm_auto()  # the first Tidy up! after switching auto-sort on starts it
        self._scan()
        self._update_folder_cards()
        self._show_panel()
        self._refresh_history()
        self.status_var.set(f"Sorted {plural(moved, 'file')} at {datetime.now():%I:%M %p}.")
        if moved and not errors and self.state() != "withdrawn":
            self._celebrate()
        else:
            self._update_mood()

    # ------------------------------------------------------------------ undo

    def _undo_last(self) -> None:
        runs = self.history.latest_undoable_batch()
        if not runs:
            messagebox.showinfo(APP_NAME, "There's nothing to undo yet.", parent=self)
            return
        self._confirm_undo(runs)

    def _undo_run(self, run_id: str) -> None:
        run = self.history.get(run_id)
        if run is None:
            return
        if run.get("undone"):
            messagebox.showinfo(APP_NAME, "That tidy-up has already been undone.", parent=self)
            return
        self._confirm_undo([run])

    def _confirm_undo(self, runs: list[dict]) -> None:
        if self.busy:
            return
        total = sum(len(r["moves"]) for r in runs)
        folders = "\n".join(r["folder"] for r in runs)
        if not messagebox.askyesno(
                APP_NAME, f"Undo the tidy-up from {fmt_time(runs[0]['time'])}?\n\n{folders}\n\n"
                          f"{plural(total, 'file')} will go back to where they were.", parent=self):
            return

        def work():
            restored, problems = 0, []
            for run in runs:
                r, p = engine.undo_run(run)
                self.history.mark_undone(run["id"])
                restored += r
                problems += p
            return restored, problems
        self._run_in_background(work, self._after_undo, "Undoing...")

    def _after_undo(self, result) -> None:
        restored, problems = result
        self.phase = "idle"
        self.celebrating = False
        self._refresh_everything()
        self._refresh_history()
        self.status_var.set(f"Undone: put {plural(restored, 'file')} back at {datetime.now():%I:%M %p}.")
        if problems:
            self._show_problems("Undo finished, with some notes:", problems)

    # ------------------------------------------------------------------ history

    def _refresh_history(self) -> None:
        p = self.px
        inner = self.hist_list.inner
        for widget in inner.winfo_children():
            widget.destroy()
        runs = [r for r in reversed(self.history.runs()) if "id" in r][:100]
        if not runs:
            empty = tk.Frame(inner, bg=WHITE)
            empty.pack(fill="x", padx=p(16), pady=p(16))
            tk.Label(empty, image=self.sprites.get("faces/front.png", 2), bg=WHITE).pack(side="left")
            tk.Label(empty, text="Nothing tidied yet. Each tidy-up will show up here, and each one can be undone.",
                     font=self.f_body, bg=WHITE, fg=MUTED).pack(side="left", padx=(p(14), 0))
            return
        for i, run in enumerate(runs):
            row = tk.Frame(inner, bg=WHITE)
            row.pack(fill="x")
            if i:
                tk.Frame(row, bg=LINE, height=p(2)).pack(fill="x")
            line = tk.Frame(row, bg=WHITE)
            line.pack(fill="x", padx=p(14), pady=p(8))
            undone = bool(run.get("undone"))
            auto = run.get("source") == "auto"
            art = "faces/front.png" if undone else ("faces/smug.png" if auto else "faces/happy.png")
            tk.Label(line, image=self.sprites.get(art, 2), bg=WHITE).pack(side="left")
            undo = PixelButton(line, "Undo", lambda rid=run["id"]: self._undo_run(rid), app=self, bg=WHITE)
            undo.set_enabled(not undone and not self.busy)
            undo.pack(side="right")
            tk.Label(line, text="Undone" if undone else "Can undo", font=self.f_small_b, bg=WHITE,
                     fg=MUTED).pack(side="right", padx=p(14))
            text = tk.Frame(line, bg=WHITE)
            text.pack(side="left", fill="x", expand=True, padx=(p(14), 0))
            n = len(run.get("moves", []))
            tk.Label(text, text=f"{plural(n, 'file')} from {Path(run.get('folder', '')).name}",
                     font=self.f_body_b, bg=WHITE, fg=INK, anchor="w").pack(fill="x")
            meta = tk.Frame(text, bg=WHITE)
            meta.pack(fill="x")
            tk.Label(meta, text=f"{fmt_time(run.get('time', ''))}  ·  {'Automatic' if auto else 'Tidy up!'}  ·  ",
                     font=self.f_small, bg=WHITE, fg=MUTED).pack(side="left")
            link(meta, "Open folder", lambda f=run.get("folder", ""): self._open_folder(f), app=self,
                 bg=WHITE).pack(side="left")

    # ------------------------------------------------------------------ categories

    def _build_name_rules_card(self, parent) -> tk.Frame:
        """The "Send files by name" box: course folders and code words."""
        p = self.px
        holder, card = shadow_card(parent, self, bg=PAGE)
        box = tk.Frame(card, bg=WHITE)
        box.pack(fill="x", padx=p(16), pady=p(14))
        tk.Label(box, text="Send files by name", font=self.f_h2, bg=WHITE, fg=INK, anchor="w").pack(fill="x")
        self._wrap(tk.Label(box, text="Checked before file types: course folders first, then code words. Capitals, "
                                      "spaces, dashes and underscores don't matter, so ELECTENG101, electeng 101 "
                                      "and ElectEng_101 all count.", font=self.f_small, bg=WHITE, fg=MUTED)).pack(
            fill="x", pady=(p(2), p(10)))

        def section(title, button_text, command, help_text):
            head = tk.Frame(box, bg=WHITE)
            head.pack(fill="x", pady=(p(4), 0))
            tk.Label(head, text=title, font=self.f_body_b, bg=WHITE, fg=INK).pack(side="left")
            PixelButton(head, button_text, command, app=self, bg=WHITE, pady=4).pack(side="right")
            self._wrap(tk.Label(box, text=help_text, font=self.f_small, bg=WHITE, fg=MUTED)).pack(
                fill="x", pady=(p(2), p(6)))

        def rule_row(icon, title, detail, actions, detail_side="end"):
            row = tk.Frame(box, bg=CREAM, highlightthickness=p(2), highlightbackground=LINE)
            row.pack(fill="x", pady=(0, p(6)))
            tk.Label(row, image=self.category_sprite(icon, 1.5), bg=CREAM).pack(side="left", padx=p(8), pady=p(6))
            links = tk.Frame(row, bg=CREAM)
            links.pack(side="right", padx=p(10))
            for k, (label, cmd) in enumerate(actions):
                if k:
                    tk.Label(links, text=" · ", font=self.f_small, bg=CREAM, fg=MUTED).pack(side="left")
                link(links, label, cmd, app=self, bg=CREAM).pack(side="left")
            text = tk.Frame(row, bg=CREAM)
            text.pack(side="left", fill="x", expand=True, pady=p(6))
            title_label = tk.Label(text, font=self.f_body_b, bg=CREAM, fg=INK, anchor="w", width=1)
            title_label.pack(fill="x")
            self._fit_on_resize(title_label, title, self.f_body_b, side="start")
            detail_label = tk.Label(text, font=self.f_small, bg=CREAM, fg=MUTED, anchor="w", width=1)
            detail_label.pack(fill="x")
            self._fit_on_resize(detail_label, detail, self.f_small, side=detail_side)

        section("Course folders", "+ Add course folder", self._add_course_root,
                "Pick a folder that holds your course folders. Folders named after a course code "
                "(like ELECTENG 101) are found anywhere inside it, even inside year or semester folders, "
                "and a new course folder works straight away. If a course is in more than one place, "
                "the newest year or semester is used.")
        if not self.settings.course_roots:
            tk.Label(box, text="No course folders yet.", font=self.f_small, bg=WHITE, fg=MUTED,
                     anchor="w").pack(fill="x", pady=(0, p(6)))
        for root in self.settings.course_roots:
            codes = sorted({c.name for c in engine.course_folders(root)}, key=str.lower)
            detail = (f"{plural(len(codes), 'course')}: " + ", ".join(codes) if codes else
                      "No course folders inside yet (they're named after a course code, like ELECTENG 101)")
            if not Path(root).is_dir():
                detail = "Can't find this folder any more."
            rule_row("", root, detail,
                     [("Open", lambda r=root: self._open_folder(r)),
                      ("Remove", lambda r=root: self._remove_course_root(r))])

        section("Code words", "+ Add code word", self._add_keyword_rule,
                "A file whose name contains the word goes straight to the folder you pick, "
                "for example invoice → Finance.")
        if not self.settings.keyword_rules:
            tk.Label(box, text="No code words yet.", font=self.f_small, bg=WHITE, fg=MUTED,
                     anchor="w").pack(fill="x", pady=(0, p(6)))
        for i, rule in enumerate(self.settings.keyword_rules):
            rule_row("Code word", f'"{rule["word"]}"', "→ " + rule["folder"],
                     [("Open", lambda f=rule["folder"]: self._open_folder(f)),
                      ("Remove", lambda k=i: self._remove_keyword_rule(k))], detail_side="start")
        return holder

    def _refresh_skipped_row(self) -> None:
        """'Excluded: ELECTENG 101 (Include)  Other (Include)' on the Categories page; wraps to fit."""
        row = self.skipped_row
        row.clear()
        if not self.settings.skipped_groups:
            row.add(tk.Label(row, text="Nothing is excluded. To leave a group alone, click \"Exclude\" on it "
                                       "in a Preview.", font=self.f_small, bg=CREAM, fg=MUTED))
            return
        row.add(tk.Label(row, text="Excluded (left where they are):", font=self.f_body_b, bg=CREAM, fg=INK))
        for key in self.settings.skipped_groups:
            item = tk.Frame(row, bg=CREAM)
            tk.Label(item, text=self._group_name(key) + " ", font=self.f_body, bg=CREAM, fg=INK).pack(side="left")
            link(item, "Include", lambda k=key: self._include_group(k), app=self, bg=CREAM).pack(side="left")
            row.add(item)

    def _cat_columns_for(self, width: int) -> int:
        return 3 if width >= self.px(640) else 2

    def _on_cat_resize(self, event) -> None:
        cols = self._cat_columns_for(event.width)
        if cols != self._cat_cols:  # the window got wider or narrower: re-flow the file-type cards
            self._cat_cols = cols
            self.after_idle(self._refresh_categories)

    def _refresh_categories(self) -> None:
        p = self.px
        self._refresh_skipped_row()
        inner = self.cat_scroll.inner
        for widget in inner.winfo_children():
            widget.destroy()
        cols = self._cat_cols
        for c in range(3):
            inner.columnconfigure(c, weight=1 if c < cols else 0, uniform="cat" if c < cols else "")
        self._build_name_rules_card(inner).grid(row=0, column=0, columnspan=cols, sticky="nsew",
                                                padx=(0, p(14)), pady=(0, p(20)))
        tk.Label(inner, text="File types", font=self.f_h2, bg=PAGE, fg=INK, anchor="w").grid(
            row=1, column=0, columnspan=cols, sticky="w", pady=(0, p(8)))
        entries = list(self.settings.categories.items()) + [(engine.OTHER, None)]
        for i, (name, exts) in enumerate(entries):
            holder, card = shadow_card(inner, self, bg=PAGE)
            holder.grid(row=2 + i // cols, column=i % cols, sticky="nsew", padx=(0, p(14)), pady=(0, p(14)))
            row = tk.Frame(card, bg=WHITE)
            row.pack(fill="both", expand=True, padx=p(10), pady=p(10))
            icon = tk.Label(row, image=self.category_sprite(name), bg=WHITE)
            icon.pack(side="left", anchor="n")
            text = tk.Frame(row, bg=WHITE)
            text.pack(side="left", fill="x", expand=True, padx=(p(10), 0))
            title = self._wrap(tk.Label(text, text=name, font=self.f_body_b, bg=WHITE, fg=INK))
            title.pack(fill="x")
            if exts is None:
                detail = ("Anything not listed in another category" if self.settings.other_folder
                          else "Unknown file types stay where they are (turned off above)")
            else:
                detail = ", ".join(exts)
            info = self._wrap(tk.Label(text, text=detail, font=self.f_small, bg=WHITE, fg=MUTED))
            info.pack(fill="x")
            where = [info]
            place = self.settings.category_locations.get(name)
            if place and self.settings.mode != "month":  # a folder of its own, not inside each tidied folder
                where.append(self._wrap(tk.Label(text, text=f"Folder: {Path(place) / name}", font=self.f_small,
                                                 bg=WHITE, fg=CHIP_FG)))
                where[-1].pack(fill="x", pady=(p(2), 0))
            if exts is not None:
                for widget in (card, row, icon, text, title, *where):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda e, n=name: self._edit_category(n))

        # The last box in the grid adds a new file type.
        i = len(entries)
        holder, card = shadow_card(inner, self, bg=PAGE, fill=CREAM)
        holder.grid(row=2 + i // cols, column=i % cols, sticky="nsew", padx=(0, p(14)), pady=(0, p(14)))
        row = tk.Frame(card, bg=CREAM)
        row.pack(fill="both", expand=True, padx=p(10), pady=p(10))
        icon = tk.Label(row, image=self.sprites.compose("add", ICON_COLOURS[2], 2), bg=CREAM)  # yellow tile
        icon.pack(side="left", anchor="n")
        text = tk.Frame(row, bg=CREAM)
        text.pack(side="left", fill="x", expand=True, padx=(p(10), 0))
        title = self._wrap(tk.Label(text, text="Add file type", font=self.f_body_b, bg=CREAM, fg=INK))
        title.pack(fill="x")
        info = self._wrap(tk.Label(text, text="Your own folder, file types and logo", font=self.f_small,
                                   bg=CREAM, fg=MUTED))
        info.pack(fill="x")
        for widget in (card, row, icon, text, title, info):
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda e: self._add_category())
        self.add_type_box = card

    def _validate_category(self, name: str, exts: list[str], original: str | None = None) -> str | None:
        error = engine.validate_category_name(name)
        if error:
            return error
        if name.lower() == engine.OTHER.lower():
            return '"Other" is used for files of unknown types. Please choose another name.'
        for other in self.settings.categories:
            if other != original and other.lower() == name.lower():
                return f'There\'s already a category called "{other}".'
        if not exts:
            return "Add at least one file type."
        for other, other_exts in self.settings.categories.items():
            if other == original:
                continue
            clash = sorted(set(exts) & set(other_exts))
            if clash:
                verb = "is" if len(clash) == 1 else "are"
                return f'{", ".join(clash)} {verb} already in "{other}". Remove it there first.'
        return None

    def _categories_changed(self) -> None:
        engine.clear_course_cache()  # look for course folders afresh
        self._save()
        self._refresh_categories()
        self._after_rules_changed()

    def _after_rules_changed(self) -> None:
        if self.phase == "preview":
            self.plans = self._plan_all(quiet=True, include_skipped=True)
            if not any(self.plans.values()):
                self.phase = "idle"
        self._refresh_everything()

    def _add_category(self, wait: bool = True) -> "CategoryDialog":
        dlg = CategoryDialog(self, "Add file type", self._validate_category, wait=wait)
        if wait:
            self._finish_add_category(dlg)
        return dlg

    def _finish_add_category(self, dlg: "CategoryDialog") -> None:
        if dlg.result and dlg.result[0] == "save":
            _, name, exts = dlg.result
            self.settings.categories[name] = exts
            spec = dlg.icon_spec()
            if spec:
                self.settings.category_icons[name] = spec
            self._categories_changed()

    def _edit_category(self, old: str, wait: bool = True) -> "CategoryDialog | None":
        if old not in self.settings.categories:
            return None
        dlg = CategoryDialog(self, "Edit file type",
                             lambda n, e: self._validate_category(n, e, original=old),
                             name=old, exts=", ".join(self.settings.categories[old]), can_remove=True,
                             icon=self.settings.category_icons.get(old), wait=wait)
        if wait:
            self._finish_edit_category(dlg, old)
        return dlg

    def _finish_edit_category(self, dlg: "CategoryDialog", old: str) -> None:
        if not dlg.result:
            return
        if dlg.result[0] == "remove":
            if messagebox.askyesno(APP_NAME, f'Remove the "{old}" file type?\n\n'
                                             "Files already sorted into that folder stay where they are.",
                                   parent=self):
                del self.settings.categories[old]
                self.settings.category_icons.pop(old, None)
                self.settings.category_locations.pop(old, None)
                self._categories_changed()
            return
        _, name, exts = dlg.result
        self.settings.categories = {(name if k == old else k): (exts if k == old else v)
                                    for k, v in self.settings.categories.items()}
        spec = self.settings.category_icons.pop(old, None)
        if dlg.icon_changed:
            spec = dlg.icon_spec()
        if spec:
            self.settings.category_icons[name] = spec
        place = self.settings.category_locations.pop(old, None)  # renamed: its folder stays where you chose
        if place:
            self.settings.category_locations[name] = place
        self._categories_changed()

    def _add_course_root(self) -> None:
        path = filedialog.askdirectory(parent=self, mustexist=True,
                                       title="Choose a folder that holds your course folders")
        if not path:
            return
        path = str(Path(path))
        problem = engine.folder_problem(path)
        if problem:
            messagebox.showwarning(APP_NAME, f"{path}\n\n{problem}", parent=self)
            return
        if any(Path(r).resolve() == Path(path).resolve() for r in self.settings.course_roots):
            self.status_var.set(f"{path} is already a course folder.")
            return
        engine.clear_course_cache()
        codes = sorted({c.name for c in engine.course_folders(path)}, key=str.lower)
        if not codes and not messagebox.askyesno(
                APP_NAME, f"{path}\n\nThere are no course folders in this folder yet, or in the folders "
                          "inside it. Course folders are named after a course code, like \"ELECTENG 101\".\n\n"
                          "Add it anyway? Course folders you create in it later will be used automatically.",
                parent=self):
            return
        self.settings.course_roots.append(path)
        self._categories_changed()
        self.status_var.set(f"Added {Path(path).name}: "
                            + (f"found {plural(len(codes), 'course')}" if codes else "no courses yet") + ".")

    def _remove_course_root(self, root: str) -> None:
        if root in self.settings.course_roots:
            self.settings.course_roots.remove(root)
            self._categories_changed()
            self.status_var.set(f"Removed {Path(root).name}. Files already sorted stay where they are.")

    def _add_keyword_rule(self) -> None:
        dlg = WordRuleDialog(self, self._validate_keyword_rule)
        if dlg.result:
            word, folder = dlg.result
            self.settings.keyword_rules.append({"word": word, "folder": folder})
            self._categories_changed()
            self.status_var.set(f'Files with "{word}" in their name will go to {Path(folder).name}.')

    def _validate_keyword_rule(self, word: str, folder: str) -> str | None:
        key = "".join(c for c in word.lower() if c.isalnum())
        if len(key) < 3:
            return "The code word needs at least 3 letters or numbers."
        for rule in self.settings.keyword_rules:
            if "".join(c for c in rule["word"].lower() if c.isalnum()) == key:
                return f'There\'s already a rule for "{rule["word"]}".'
        if not folder:
            return "Choose the folder these files should go to."
        problem = engine.target_problem(folder)
        if problem:
            return problem
        if any(Path(f).resolve() == Path(folder).resolve() for f in self.settings.folders):
            return "That's one of the folders being tidied. Choose a folder to send the files to."
        return None

    def _remove_keyword_rule(self, index: int) -> None:
        if 0 <= index < len(self.settings.keyword_rules):
            rule = self.settings.keyword_rules.pop(index)
            self._categories_changed()
            self.status_var.set(f'Removed the code word "{rule["word"]}".')

    def _reset_categories(self) -> None:
        if messagebox.askyesno(APP_NAME, "Replace your file types (and their logos and folder locations) "
                                         "with the built-in ones?", parent=self):
            self.settings.categories = default_categories()
            self.settings.category_icons = {}
            self.settings.category_locations = {}
            self._categories_changed()

    def _on_options_changed(self, *_args) -> None:
        label = self.mode_var.get()
        self.settings.mode = next(k for k, v in MODE_LABELS.items() if v == label)
        self.settings.other_folder = self.other_var.get()
        self.settings.skip_shortcuts = self.shortcut_var.get()
        self._save()
        self._refresh_categories()
        self._after_rules_changed()

    # ------------------------------------------------------------------ automatic sorting

    def _flip_auto(self) -> None:
        self.auto_var.set(not self.auto_var.get())
        self._toggle_auto()

    def _toggle_auto(self) -> None:
        if self.auto_var.get():
            if not messagebox.askyesno(
                    APP_NAME, "Automatic sorting keeps these folders tidy by itself.\n\n"
                              "Nothing moves straight away: it starts after you click Tidy up! once, "
                              "so the first tidy-up is always yours to check. After that, new files are "
                              f"sorted every {self.interval_var.get()} without asking (each is left for a "
                              "minute first, so downloads can finish).\n\n"
                              "Nothing is ever deleted, and every sort can be undone from the History "
                              "tab.\n\nTurn on automatic sorting?", parent=self):
                self.auto_var.set(False)
                self.auto_switch.set(False)
                return
            self._set_auto(True)
            self._offer_startup()
        else:
            self._set_auto(False)

    def _set_auto(self, on: bool) -> None:
        """Switch auto-sort on or off. Switching it on waits for the next Tidy up! before it runs."""
        self.settings.auto_sort = on
        self.settings.auto_armed = False
        self.auto_var.set(on)
        self.auto_switch.set(on)
        self._save()
        self._stop_auto()
        self._update_auto_label()
        self._update_mood()
        if self.tray:
            self.tray.refresh_menu()
        if on:
            self.status_var.set("Automatic sorting is on. It starts after you click Tidy up! once.")

    def _arm_auto(self) -> None:
        """After a Tidy up!, start auto-sort if it was switched on and waiting."""
        if self.settings.auto_sort and not self.settings.auto_armed:
            self.settings.auto_armed = True
            self._save()
            self._start_auto()
            self._update_auto_label()
            if self.tray:
                self.tray.refresh_menu()

    def _start_auto(self) -> None:
        if self.auto:
            return

        def on_run(run, errors):  # called from the background thread
            self.events.put(lambda: self._on_auto_run(run, errors))
        self.auto = AutoSorter(self.settings, self.history, on_run)
        self.auto.start()

    def _stop_auto(self) -> None:
        if self.auto:
            self.auto.stop()
            self.auto = None

    def _update_auto_label(self) -> None:
        self.auto_face.pack_forget()
        self.auto_wait.pack_forget()
        if self.auto:
            self.auto_state_var.set("On. Keeps working in the tray after you close the window."
                                    if self.tray and self.settings.close_to_tray
                                    else "On. Runs while this window is open.")
            self.auto_face.pack(side="right")
        elif self.settings.auto_sort:
            self.auto_state_var.set("On, waiting: starts after you click Tidy up! once.")
            self.auto_wait.pack(anchor="w", padx=self.px(14), pady=(self.px(2), 0), before=self.auto_row2)
        else:
            self.auto_state_var.set("Off.")

    def _on_interval_changed(self, *_args) -> None:
        self.settings.interval_seconds = dict(INTERVALS).get(self.interval_var.get(), 30)
        self._save()

    def _on_auto_run(self, run: dict, errors: list[str]) -> None:
        moved = len(run.get("moves", []))
        if moved:
            where = Path(run["folder"]).name
            self.status_var.set(f"Auto-sorted {plural(moved, 'file')} in {where} "
                                f"at {datetime.now():%I:%M %p}.")
            if self.tray:
                self.tray.set_tooltip(f"{APP_NAME}\nLast sorted {plural(moved, 'file')} "
                                      f"at {datetime.now():%I:%M %p}")
            if self.phase == "preview":
                self.phase = "idle"
            self._refresh_everything()
            self._refresh_history()
            if self.state() != "withdrawn" and not self.busy:
                self._play_animation_once()  # show the buddy gobbling what auto-sort just tidied
        if errors:
            self.status_var.set(f"Auto-sort couldn't move {plural(len(errors), 'file')}: {errors[0]}")

    # ------------------------------------------------------------------ start-up & tray

    def _toggle_startup(self) -> None:
        try:
            if self.startup_var.get():
                startup.enable()
                self.status_var.set("Tidy Folders will start by itself when you sign in to Windows.")
            else:
                startup.disable()
                self.status_var.set("Tidy Folders won't start by itself anymore.")
        except OSError as e:
            self.startup_var.set(startup.is_enabled())
            messagebox.showerror(APP_NAME, f"Couldn't change the start-up setting:\n\n{e}", parent=self)

    def _offer_startup(self) -> None:
        """Right after automatic sorting is switched on, offer to make it survive restarts."""
        if not startup.supported() or startup.is_enabled():
            return
        if messagebox.askyesno(
                APP_NAME, "Also start Tidy Folders when you sign in to Windows?\n\n"
                          "It opens quietly in the tray (next to the clock), so your folders "
                          "stay tidy without you having to open it. You can change this anytime "
                          "at the bottom of the Sort page.", parent=self):
            self.startup_var.set(True)
            self._toggle_startup()

    def _toggle_close_to_tray(self) -> None:
        self.settings.close_to_tray = self.tray_var.get()
        self._save()
        self._update_auto_label()

    def _create_tray(self) -> "tray_mod.TrayIcon | None":
        # Tray icons are 16px at 100% scaling, 24px at 150%, 32px at 200%.
        size = "16" if self.scale < 1.5 else ("24" if self.scale < 2 else "32")
        icon = ASSETS / "logo" / f"{size}.png"
        if not icon.exists():
            icon = self.icon_path
        if not tray_mod.available() or not icon.exists():
            return None

        def on_ui_thread(fn):  # tray clicks arrive on the tray's thread
            return lambda: self.events.put(fn)
        try:
            return tray_mod.TrayIcon(
                icon,
                on_open=on_ui_thread(self._show_window),
                on_sort_now=on_ui_thread(self._tray_sort_now),
                on_toggle_auto=on_ui_thread(self._tray_toggle_auto),
                is_auto_on=lambda: self.settings.auto_sort,
                on_quit=on_ui_thread(self._quit),
            )
        except Exception:
            return None

    def _show_window(self) -> None:
        self.deiconify()
        self._set_window_icons()  # a window first shown from the tray gets its icons now
        if self.state() == "iconic":
            self.state("normal")
        self.lift()
        self.attributes("-topmost", True)  # bring it in front of other windows...
        self.after(300, lambda: self.attributes("-topmost", False))  # ...without pinning it there
        self.focus_force()
        if not self.busy and self.phase != "preview":
            self._refresh_everything()
        self._refresh_history()

    def _tray_sort_now(self) -> None:
        if self.busy or not self.tray:
            return
        if not self.settings.folders:
            self.tray.notify("No folders to tidy yet. Open Tidy Folders and add one first.")
            return
        plans = self._plan_all(quiet=True)
        total = sum(len(m) for m in plans.values())
        if total == 0:
            self._arm_auto()
            self.tray.notify("Nothing to sort. Your folders are already tidy.")
            return
        batch = uuid.uuid4().hex[:12]

        def work():
            return [engine.apply_moves(moves, folder, "manual", self.history, batch)
                    for folder, moves in plans.items()]

        def done(results):
            self._after_sort(results, quiet=True)
            moved = sum(len(run["moves"]) for run, _ in results)
            failed = sum(len(errs) for _, errs in results)
            message = f"Moved {plural(moved, 'file')} into folders."
            if failed:
                message += f" {plural(failed, 'file')} couldn't be moved (open in another program?)."
            self.tray.notify(message + " To undo, open Tidy Folders and click Undo.")
        self._run_in_background(work, done, f"Sorting {plural(total, 'file')}...",
                                animate=self.state() != "withdrawn")

    def _tray_toggle_auto(self) -> None:
        turn_on = not self.settings.auto_sort
        self._set_auto(turn_on)
        if self.tray:
            self.tray.notify(
                "Automatic sorting is on. It starts after you click Sort now (or Tidy up!) once."
                if turn_on else "Automatic sorting is off.")

    def _listen_for_show_requests(self) -> None:
        """Opening Tidy Folders again (e.g. from the Start menu) shows this window."""
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                          wintypes.LPCWSTR)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        handle = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        if not handle:
            return

        def wait():
            while kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:  # WAIT_OBJECT_0
                self.events.put(self._show_window)
        threading.Thread(target=wait, name="tidy-show-requests", daemon=True).start()

    def _on_close(self) -> None:
        if self.tray and self.settings.close_to_tray:
            self.withdraw()
            if not self.settings.tray_hint_shown:
                self.settings.tray_hint_shown = True
                self._save()
                self.tray.notify("Tidy Folders is still running, next to the clock (you may need "
                                 "to click the ^ arrow). Click the icon to open it, or "
                                 "right-click it to quit.")
            return
        self._quit()

    def _quit(self) -> None:
        self._stop_auto()
        if self.tray:
            self.tray.stop()
        self.destroy()


# ====================================================================== start-up

_instance_mutex = None  # held for the life of the process


def _another_copy_running() -> bool:
    """True if Tidy Folders is already open (two copies would fight over the same files)."""
    import ctypes
    from ctypes import wintypes
    global _instance_mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\TidyFoldersSingleInstance")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def _ask_running_copy_to_show() -> bool:
    """Tell the copy that's already running (maybe hidden in the tray) to show its window."""
    import ctypes
    from ctypes import wintypes
    ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY: let it come to the front
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenEventW(0x0002, False, SHOW_EVENT_NAME)  # EVENT_MODIFY_STATE
    if not handle:
        return False
    kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)
    return True


def main() -> None:
    start_hidden = "--tray" in sys.argv[1:]
    if sys.platform == "win32":
        import ctypes
        if _another_copy_running():
            if not start_hidden and not _ask_running_copy_to_show():
                ctypes.windll.user32.MessageBoxW(None, f"{APP_NAME} is already open.", APP_NAME, 0x40)
            return
        try:  # group under our own icon in the taskbar, not Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TidyFolders.App")
        except Exception:
            pass
        try:  # crisp text on high-resolution screens
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App(start_hidden=start_hidden).mainloop()


if __name__ == "__main__":
    main()
