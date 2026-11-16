"""The logo picker in the file type window: the blue "chosen" box fits tightly around each tile (ink on
blue tiles), the yellow colour, and an uploaded picture. Measured on a real screenshot."""
from PIL import Image

from helpers import SHOTS, check, finish, pump, setup, shot, use

work = setup("logo-picker")
small = work / "small-logo.png"  # 12x12: gets see-through edges when fitted to 24x21
Image.new("RGBA", (12, 12), (40, 160, 90, 255)).save(small)

from tidy_folders import gui  # noqa: E402

gui.filedialog.askopenfilename = lambda **kw: str(small)


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def hugs(tile, picture):
    """Just inside the box, in the middle of each side, is the tile, not the page."""
    ring = int(tile.cget("highlightthickness"))
    ox, oy = tile.winfo_rootx() - dlg.winfo_rootx(), tile.winfo_rooty() - dlg.winfo_rooty()
    w, h = tile.winfo_width(), tile.winfo_height()
    box, page = hex_rgb(tile.cget("highlightbackground")), hex_rgb(gui.PAGE)
    result = {"box stands out from the tile": box != picture.getpixel((ox + ring + 1, oy + ring + 1))}
    for side, (bx, by, ix, iy) in {
            "left": (ox + ring - 1, oy + h // 2, ox + ring, oy + h // 2),
            "right": (ox + w - ring, oy + h // 2, ox + w - ring - 1, oy + h // 2),
            "top": (ox + w // 2, oy + ring - 1, ox + w // 2, oy + ring),
            "bottom": (ox + w // 2, oy + h - ring, ox + w // 2, oy + h - ring - 1)}.items():
        result[side] = picture.getpixel((bx, by)) == box and picture.getpixel((ix, iy)) != page
    return result


def snap(name):
    shot(name, dlg)
    return Image.open(SHOTS / name).convert("RGB")


app = use(gui.App())
pump(1.0)
check("the 3rd colour is yellow", gui.ICON_COLOURS[2] == "#E09F00")
dlg = app._add_category(wait=False)
pump(0.5)
zoom = app.sprites.zoom_for(2)
for colour in (gui.ICON_COLOURS[0], gui.ICON_COLOURS[2], gui.ICON_COLOURS[5]):
    for g in range(1, 9):
        dlg._pick_glyph(g)
        dlg._pick_colour(colour)
        pump(0.1)
        img = dlg.tiles[g - 1].cget("image")
        size = (app.tk.call("image", "width", img), app.tk.call("image", "height", img))
        check(f"symbol {g} on {colour}: tile has no see-through strips", size == (20 * zoom, 21 * zoom))
        if g in (1, 5, 8):  # screenshots take a moment: measure a few
            result = hugs(dlg.tiles[g - 1], snap("logo-picker.png"))
            check(f"symbol {g} on {colour}: the box fits the tile {result}", all(result.values()))
dlg._pick_colour(gui.ICON_COLOURS[2])
check("the logo uses the yellow", dlg.icon_spec()["colour"] == "#E09F00")
dlg._upload()
pump(0.3)
result = hugs(dlg.tiles[8], snap("logo-picker-upload.png"))
check(f"an uploaded picture with see-through edges: the box fits it {result}", all(result.values()))
dlg.destroy()
finish("LOGO PICKER")
