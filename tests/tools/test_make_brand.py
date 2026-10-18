"""The brand drawing: what it writes, where, how `--check` judges a tree, and its parts.

`tests/test_repository.py` compares the committed images with a fresh drawing; these
tests run the command line against a temporary root, so the repository is never written.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageFont
import pytest

from tools import make_brand


@pytest.fixture(scope="module")
def drawn_files() -> dict[Path, bytes]:
    return make_brand.render_files()


def test_main_writes_every_image_to_brand_and_to_the_brands_layout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert make_brand.main(["--root", str(tmp_path)]) == make_brand.EXIT_OK

    printed = capsys.readouterr().out.split()
    for name in make_brand.ASSET_NAMES:
        top = tmp_path / "brand" / name
        layout = tmp_path / "brand" / "brands" / "custom_integrations" / "device_routines" / name
        assert top.read_bytes() == layout.read_bytes()
        assert str(Path("brand") / name) in printed
    assert len(printed) == 2 * len(make_brand.ASSET_NAMES)


def test_check_passes_on_a_tree_it_wrote(tmp_path: Path) -> None:
    make_brand.write(tmp_path)

    assert make_brand.main(["--check", "--root", str(tmp_path)]) == make_brand.EXIT_OK


def test_check_names_a_changed_a_missing_and_a_stray_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_brand.write(tmp_path)
    (tmp_path / make_brand.BRAND_DIR / "icon.png").write_bytes(b"not the drawing")
    (tmp_path / make_brand.BRANDS_LAYOUT_DIR / "logo@2x.png").unlink()
    (tmp_path / make_brand.BRANDS_LAYOUT_DIR / "old_icon.png").write_bytes(b"left over")

    assert make_brand.main(["--check", "--root", str(tmp_path)]) == make_brand.EXIT_DIFFERENT

    assert capsys.readouterr().out.splitlines() == [
        f"{make_brand.BRAND_DIR / 'icon.png'}: differs from a fresh drawing",
        f"{make_brand.BRANDS_LAYOUT_DIR / 'logo@2x.png'}: missing",
        f"{make_brand.BRANDS_LAYOUT_DIR / 'old_icon.png'}: not drawn by tools/make_brand.py",
    ]


def test_check_writes_nothing(tmp_path: Path) -> None:
    assert make_brand.main(["--check", "--root", str(tmp_path)]) == make_brand.EXIT_DIFFERENT

    assert list(tmp_path.iterdir()) == []


def test_the_drawing_is_deterministic(drawn_files: dict[Path, bytes]) -> None:
    assert make_brand.render_files() == drawn_files


def test_render_all_draws_the_names_in_order() -> None:
    assert tuple(make_brand.render_all()) == make_brand.ASSET_NAMES


def test_the_words_are_aileron_regular_with_the_basic_layout() -> None:
    """Pillow's bundled CC0 font; Raqm, where a platform has it, must not move a glyph."""
    font = make_brand.wordmark_font(64)

    assert font.getname() == ("Aileron", "Regular")
    assert font.layout_engine == ImageFont.Layout.BASIC


def test_the_wordmark_fills_its_height_with_the_capitals_centered() -> None:
    words = make_brand.draw_wordmark(128, make_brand.TEXT_ON_LIGHT)
    alpha = words.getchannel("A")
    _, top, _, bottom = alpha.getbbox() or (0, 0, 0, 0)

    assert words.height == 128
    assert abs(top - (128 - bottom)) <= 2
    assert words.getpixel((0, 0)) == (*make_brand.TEXT_ON_LIGHT[:3], 0)


def test_the_logo_is_the_icon_then_the_words(drawn_files: dict[Path, bytes]) -> None:
    logo = make_brand.draw_logo(128, make_brand.TEXT_ON_DARK)
    icon = make_brand.draw_icon(128)

    assert logo.height == 128
    assert logo.crop((0, 0, 128, 128)).tobytes() == icon.tobytes()
    assert drawn_files[make_brand.BRAND_DIR / "dark_logo.png"] == make_brand.encode(logo)


def test_an_empty_rectangle_draws_nothing() -> None:
    pen = make_brand._Pen(64)

    pen.rect(10, 10, 10, 20, make_brand.WHITE)
    pen.rect(10, 20, 30, 20, make_brand.WHITE)

    assert pen.image.getbbox() is None


def test_shapes_land_on_the_supersampled_grid() -> None:
    """A quarter unit is a whole pixel at the smallest size drawn, the 128 pixel logo."""
    pen = make_brand._Pen(make_brand.LOGO_HEIGHT)

    pen.rect(0.25, 0.5, 1.0, 1.25, make_brand.WHITE)

    assert pen.scale * 0.25 == int(pen.scale * 0.25)
    assert pen.image.getbbox() == (4, 8, 16, 20)


def test_the_icon_has_the_calendar_colors_and_a_clear_gap_around_the_clock() -> None:
    icon = make_brand.draw_icon(256)
    unit = 256 // make_brand.GRID
    cx, cy = make_brand.CLOCK_CENTER
    gap = make_brand.CLOCK_RADIUS + make_brand.CLOCK_GAP / 2

    def at(x: float, y: float) -> object:
        return icon.getpixel((int(x * unit), int(y * unit)))

    assert at(12, 40) == make_brand.BLUE  # the calendar body
    assert at(26, 18) == make_brand.BLUE_DARK  # the header band
    assert at(14, 3) == make_brand.NAVY  # a ring above the calendar
    assert at(cx - 8, cy + 8) == make_brand.WHITE  # the clock face
    assert at(cx, cy - 6) == make_brand.NAVY  # the long hand
    assert at(cx - gap * 0.7071, cy - gap * 0.7071)[3] == 0  # type: ignore[index]


def test_the_images_carry_no_metadata(drawn_files: dict[Path, bytes]) -> None:
    for path, data in drawn_files.items():
        image = Image.open(io.BytesIO(data))
        assert image.info == {}, path
