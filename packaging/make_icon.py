"""Builds the app icon (tidy_folders/assets/icon.ico) and the small logo sizes from logo/24.png.

24x24 is the hand-drawn logo: the size Windows uses for taskbar icons at 100% scaling.
Every other size is made without blurring:
  * 48: the 24 doubled (each pixel becomes a 2x2 block)
  * 32, 64, 128, 256: the biggest whole-number enlargement that fits, centred
  * 16: logo/16.png if you have drawn one, otherwise 16 of the 24 rows and columns,
    picked so both eyes stay 2 pixels wide and the tongue keeps its highlight

Usage:  python packaging/make_icon.py      (needs Pillow; build.bat installs it)
"""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "tidy_folders" / "assets"
LOGO = ASSETS / "logo"
KEEP = [1, 2, 4, 5, 7, 8, 9, 11, 12, 14, 15, 16, 18, 19, 21, 22]  # rows/columns kept for 16x16


def scaled(image: Image.Image, factor: int) -> Image.Image:
    return image.resize((image.width * factor, image.height * factor), Image.NEAREST)


def centred(image: Image.Image, size: int) -> Image.Image:
    big = scaled(image, max(1, size // image.width))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(big, ((size - big.width) // 2, (size - big.height) // 2))
    return canvas


def reduce_to_16(image: Image.Image) -> Image.Image:
    small = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    src, dst = image.load(), small.load()
    for y, sy in enumerate(KEEP):
        for x, sx in enumerate(KEEP):
            dst[x, y] = src[sx, sy]
    return small


def main() -> None:
    logo = Image.open(LOGO / "24.png").convert("RGBA")
    hand_16 = LOGO / "16_drawn.png"
    small = Image.open(hand_16).convert("RGBA") if hand_16.exists() else reduce_to_16(logo)
    small.save(LOGO / "16.png")
    centred(logo, 32).save(LOGO / "32.png")

    images = [small, logo, centred(logo, 32), scaled(logo, 2),
              centred(logo, 64), centred(logo, 128), centred(logo, 256)]
    out = ASSETS / "icon.ico"
    images[-1].save(out, format="ICO", sizes=[im.size for im in images], append_images=images[:-1])
    print("saved", out, [im.size for im in images])


if __name__ == "__main__":
    main()
