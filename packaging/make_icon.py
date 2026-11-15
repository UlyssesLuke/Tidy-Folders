"""Draws the Tidy Folders icon (a folder with sorted bars) and saves it as an .ico.

Usage:  python packaging/make_icon.py [optional-preview.png]
Needs Pillow (installed in the build environment by build.bat).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "tidy_folders" / "assets" / "icon.ico"
S = 1024  # draw big, then scale down for smooth edges


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # folder: tab, back panel, front panel
    d.rounded_rectangle((90, 150, 470, 330), radius=60, fill="#D9961A")
    d.rounded_rectangle((90, 230, 934, 860), radius=70, fill="#E5A520")
    d.rounded_rectangle((90, 330, 934, 900), radius=70, fill="#FFC940")
    # three sorted bars, each with a coloured dot
    bars = [(470, 760, "#2F7CF6"), (590, 650, "#1FB45A"), (710, 540, "#E8457E")]
    for top, right, colour in bars:
        d.rounded_rectangle((200, top, right, top + 76), radius=38, fill="#FFFFFF")
        d.ellipse((222, top + 14, 270, top + 62), fill=colour)
    return img


def main() -> None:
    big = draw()
    base = big.resize((256, 256), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base.save(OUT, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                        (64, 64), (128, 128), (256, 256)])
    print("saved", OUT)
    if len(sys.argv) > 1:  # optional preview at a few sizes
        sheet = Image.new("RGBA", (256 + 64 + 32 + 16 + 60, 256), (240, 240, 240, 255))
        x = 0
        for size in (256, 64, 32, 16):
            sheet.alpha_composite(big.resize((size, size), Image.LANCZOS), (x, 0))
            x += size + 20
        sheet.save(sys.argv[1])


if __name__ == "__main__":
    main()
