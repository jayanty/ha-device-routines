"""Draw the Device Routines brand images (PRD 11.1, plan 6.2.9 lane 23).

The icon is the integration's `mdi:calendar-clock` idea drawn in Home Assistant's flat
style: a blue calendar with two rings and a darker header band, and in front of its lower
right corner a clock with a white face whose hands show three o'clock, set apart from the
calendar by a transparent gap. The logo puts the icon next to the words "Device
Routines", set in Aileron Regular, the CC0 font Pillow bundles behind
`ImageFont.load_default(size=...)`, with a light stroke for a medium weight.

Run `python -m tools.make_brand` to write every image to `brand/` and the same bytes to
`brand/brands/custom_integrations/device_routines/`, the layout of the
`home-assistant/brands` repository. `--check` writes nothing and fails when a committed
file differs from a fresh drawing, is missing, or has no drawing.

The images are reproducible by construction. Every shape is a rectangle or a circle on
whole pixel steps of an eight times larger canvas, which Pillow fills in integers,
and the canvas is reduced by box averaging, again in integers. The words are rendered by
FreeType, whose rasterizer is fixed point, with Pillow's basic layout forced, so a platform
with the Raqm layout engine places the glyphs the same way. The same Pillow (the core pins
it) therefore draws the same image on every platform, and its PNG encoder writes the same
bytes for it.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = Path("brand")
BRANDS_LAYOUT_DIR = BRAND_DIR / "brands" / "custom_integrations" / "device_routines"

EXIT_OK = 0
EXIT_DIFFERENT = 1

# The icon is designed on a 64 unit square; every coordinate below is a multiple of a
# quarter unit, so it lands on a whole pixel of every supersampled canvas drawn here.
GRID = 64
SUPERSAMPLE = 8
ICON_SIZE = 256
LOGO_HEIGHT = 128

Color = tuple[int, int, int, int]

CLEAR: Color = (0, 0, 0, 0)
WHITE: Color = (255, 255, 255, 255)
BLUE: Color = (3, 169, 244, 255)  # Home Assistant's primary blue, #03A9F4
BLUE_DARK: Color = (2, 136, 209, 255)  # #0288D1, the header band and the clock's rim
NAVY: Color = (1, 87, 155, 255)  # #01579B, the rings and the hands
TEXT_ON_LIGHT: Color = (33, 33, 33, 255)  # #212121, Home Assistant's primary text
TEXT_ON_DARK: Color = WHITE

# The calendar: a rounded square with a header band and two rings above it.
CALENDAR = (0.0, 7.0, 52.0, 57.0)
CALENDAR_RADIUS = 7.0
HEADER_BOTTOM = 21.0
RINGS = ((11.0, 0.0, 17.0, 14.0), (35.0, 0.0, 41.0, 14.0))

# The clock: a rim and a white face, a gap that cuts it out of the calendar, and two
# hands from the center, the long one to twelve and the short one to three.
CLOCK_CENTER = (46.0, 46.0)
CLOCK_RADIUS = 18.0
CLOCK_RIM = 4.0
CLOCK_GAP = 3.0
HAND_HALF_WIDTH = 2.0
LONG_HAND = 10.0
SHORT_HAND = 8.0

WORDMARK = "Device Routines"
WORDMARK_SIZE = 0.42  # the font size, as a share of the logo's height
WORDMARK_STROKE = 0.006  # the stroke that gives the medium weight, as a share of it
WORDMARK_GAP = 0.25  # the space between the icon and the words, as a share of it

# Every file name, in the order `render_all` draws them. The brands repository takes
# `dark_` variants for the dark theme; the icon reads on both, the words do not.
ASSET_NAMES = (
    "icon.png",
    "icon@2x.png",
    "logo.png",
    "logo@2x.png",
    "dark_logo.png",
    "dark_logo@2x.png",
)


class _Pen:
    """Fill shapes given in design units on a supersampled, transparent canvas.

    Every pixel of the canvas is either one fill color or clear, so later shapes simply
    replace earlier ones, and drawing a shape in `CLEAR` cuts it out.
    """

    def __init__(self, size: int) -> None:
        self.scale = size * SUPERSAMPLE // GRID
        self.image = Image.new("RGBA", (size * SUPERSAMPLE, size * SUPERSAMPLE), CLEAR)
        self._draw = ImageDraw.Draw(self.image)

    def _px(self, value: float) -> int:
        return round(value * self.scale)

    def rect(self, x0: float, y0: float, x1: float, y1: float, fill: Color) -> None:
        """Fill the rectangle from (x0, y0) up to, not including, (x1, y1); empty is a no-op."""
        if x1 <= x0 or y1 <= y0:
            return
        box = (self._px(x0), self._px(y0), self._px(x1) - 1, self._px(y1) - 1)
        self._draw.rectangle(box, fill=fill)

    def disc(self, cx: float, cy: float, radius: float, fill: Color) -> None:
        """Fill the circle around (cx, cy)."""
        box = (
            self._px(cx - radius),
            self._px(cy - radius),
            self._px(cx + radius) - 1,
            self._px(cy + radius) - 1,
        )
        self._draw.ellipse(box, fill=fill)

    def rounded_rect(
        self, box: tuple[float, float, float, float], radius: float, fill: Color
    ) -> None:
        """Fill a rectangle whose four corners are quarter circles of `radius`."""
        x0, y0, x1, y1 = box
        self.rect(x0 + radius, y0, x1 - radius, y1, fill)
        self.rect(x0, y0 + radius, x1, y1 - radius, fill)
        for cx in (x0 + radius, x1 - radius):
            for cy in (y0 + radius, y1 - radius):
                self.disc(cx, cy, radius, fill)

    def capsule(self, box: tuple[float, float, float, float], fill: Color) -> None:
        """Fill a rectangle whose short sides are half circles."""
        x0, y0, x1, y1 = box
        self.rounded_rect(box, min(x1 - x0, y1 - y0) / 2, fill)

    def reduced(self) -> Image.Image:
        """Return the canvas at its real size, each pixel the average of its subpixels."""
        return self.image.reduce(SUPERSAMPLE)


def draw_icon(size: int) -> Image.Image:
    """Return the square icon, `size` px wide, on a transparent background."""
    pen = _Pen(size)
    x0, y0, x1, _ = CALENDAR
    pen.rounded_rect(CALENDAR, CALENDAR_RADIUS, BLUE)
    # The header band is the calendar's top down to HEADER_BOTTOM, its corners rounded.
    pen.rounded_rect((x0, y0, x1, y0 + 2 * CALENDAR_RADIUS), CALENDAR_RADIUS, BLUE_DARK)
    pen.rect(x0, y0 + CALENDAR_RADIUS, x1, HEADER_BOTTOM, BLUE_DARK)
    for ring in RINGS:
        pen.capsule(ring, NAVY)

    cx, cy = CLOCK_CENTER
    pen.disc(cx, cy, CLOCK_RADIUS + CLOCK_GAP, CLEAR)
    pen.disc(cx, cy, CLOCK_RADIUS, BLUE_DARK)
    pen.disc(cx, cy, CLOCK_RADIUS - CLOCK_RIM, WHITE)
    half = HAND_HALF_WIDTH
    pen.capsule((cx - half, cy - LONG_HAND, cx + half, cy + half), NAVY)
    pen.capsule((cx - half, cy - half, cx + SHORT_HAND, cy + half), NAVY)
    return pen.reduced()


def wordmark_font(size: int) -> ImageFont.FreeTypeFont:
    """Return Aileron Regular at `size` px, laid out by Pillow's basic engine."""
    font = ImageFont.load_default(size=size)
    if not isinstance(font, ImageFont.FreeTypeFont):  # pragma: no cover - Pillow sans FreeType
        raise TypeError("drawing the logo needs Pillow with FreeType")
    return font.font_variant(layout_engine=ImageFont.Layout.BASIC)


def draw_wordmark(height: int, color: Color) -> Image.Image:
    """Return the words alone, `height` px tall, their capitals centered vertically."""
    big = height * SUPERSAMPLE
    font = wordmark_font(round(height * WORDMARK_SIZE) * SUPERSAMPLE)
    stroke = round(height * WORDMARK_STROKE * SUPERSAMPLE)
    left, _, right, _ = (int(edge) for edge in font.getbbox(WORDMARK, stroke_width=stroke))
    _, cap_top, _, baseline = (int(edge) for edge in font.getbbox("D"))
    top = (big - (baseline - cap_top)) // 2 - cap_top
    mask = Image.new("L", (right - left, big), 0)
    ImageDraw.Draw(mask).text(
        (-left, top), WORDMARK, font=font, fill=255, stroke_width=stroke, stroke_fill=255
    )
    alpha = mask.reduce(SUPERSAMPLE)
    words = Image.new("RGBA", alpha.size, color)
    words.putalpha(alpha)
    return words


def draw_logo(height: int, text_color: Color) -> Image.Image:
    """Return the icon and the words side by side, trimmed to what they cover."""
    icon = draw_icon(height)
    words = draw_wordmark(height, text_color)
    gap = round(height * WORDMARK_GAP)
    logo = Image.new("RGBA", (height + gap + words.width, height), CLEAR)
    logo.paste(icon, (0, 0))
    logo.alpha_composite(words, (height + gap, 0))
    return logo.crop(logo.getbbox(alpha_only=True))


def render_all() -> dict[str, Image.Image]:
    """Return every brand image by file name, in `ASSET_NAMES` order."""
    images = {
        "icon.png": draw_icon(ICON_SIZE),
        "icon@2x.png": draw_icon(2 * ICON_SIZE),
        "logo.png": draw_logo(LOGO_HEIGHT, TEXT_ON_LIGHT),
        "logo@2x.png": draw_logo(2 * LOGO_HEIGHT, TEXT_ON_LIGHT),
        "dark_logo.png": draw_logo(LOGO_HEIGHT, TEXT_ON_DARK),
        "dark_logo@2x.png": draw_logo(2 * LOGO_HEIGHT, TEXT_ON_DARK),
    }
    return {name: images[name] for name in ASSET_NAMES}


def encode(image: Image.Image) -> bytes:
    """Return the PNG bytes of `image`: no metadata, the smallest encoding Pillow finds."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_files() -> dict[Path, bytes]:
    """Return the bytes of every file, under `brand/` and under the brands layout."""
    encoded = {name: encode(image) for name, image in render_all().items()}
    files = {BRAND_DIR / name: data for name, data in encoded.items()}
    files.update({BRANDS_LAYOUT_DIR / name: data for name, data in encoded.items()})
    return files


def write(root: Path) -> list[Path]:
    """Write every file below `root` and return the relative paths written."""
    files = render_files()
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return list(files)


def check(root: Path) -> list[str]:
    """Return one line per file below `root` that differs from a fresh drawing."""
    files = render_files()
    problems: list[str] = []
    for relative, data in files.items():
        path = root / relative
        if not path.is_file():
            problems.append(f"{relative}: missing")
        elif path.read_bytes() != data:
            problems.append(f"{relative}: differs from a fresh drawing")
    for directory in (BRAND_DIR, BRANDS_LAYOUT_DIR):
        problems.extend(
            f"{path.relative_to(root)}: not drawn by tools/make_brand.py"
            for path in sorted((root / directory).glob("*.png"))
            if path.relative_to(root) not in files
        )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Write the brand images, or with `--check` compare them with a fresh drawing."""
    parser = argparse.ArgumentParser(description="Draw the Device Routines brand images.")
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)
    root: Path = args.root
    if args.check:
        problems = check(root)
        for problem in problems:
            print(problem)
        return EXIT_DIFFERENT if problems else EXIT_OK
    for relative in write(root):
        print(relative)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
