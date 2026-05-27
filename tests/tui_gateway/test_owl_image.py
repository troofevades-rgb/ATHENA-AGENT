"""Tests for ``athena.tui_gateway.owl_image.render_owl_pixels``.

The renderer is responsible for producing the half-block matrix
the Ink TUI consumes. These tests pin:

  - the output structure (width/height/rows)
  - hex color format
  - graceful fallback when Pillow or the image file is missing
  - the half-block pairing invariant (each row holds 2 source
    pixel rows; the matrix's terminal ``height`` is 1/2 of the
    underlying pixel ``out_h``)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from athena.tui_gateway.owl_image import render_owl_pixels


_HEX = re.compile(r"^#[0-9a-f]{6}$")


def test_renders_at_requested_size():
    matrix = render_owl_pixels(40, 20)
    assert matrix is not None
    # ``width`` may be less than 40 due to aspect-ratio fit, but
    # never zero, and ``height`` matches the row count exactly.
    assert 1 <= matrix["width"] <= 40
    assert 1 <= matrix["height"] <= 20
    assert matrix["height"] == len(matrix["cells"])
    # Every row should be ``width`` cells wide.
    for row in matrix["cells"]:
        assert len(row) == matrix["width"]


def test_cell_format_is_glyph_plus_two_hex_strings():
    matrix = render_owl_pixels(20, 10)
    assert matrix is not None
    sample = matrix["cells"][0][0]
    # ``[glyph, fgHex, bgHex]`` per the contract.
    assert isinstance(sample, list)
    assert len(sample) == 3
    glyph, fg, bg = sample
    assert isinstance(glyph, str) and len(glyph) == 1
    assert _HEX.match(fg), f"fg color not 6-digit hex: {fg!r}"
    assert _HEX.match(bg), f"bg color not 6-digit hex: {bg!r}"


def test_returns_none_for_invalid_target_dims():
    assert render_owl_pixels(0, 10) is None
    assert render_owl_pixels(10, 0) is None
    assert render_owl_pixels(-1, 10) is None
    assert render_owl_pixels(10, -1) is None


def test_returns_none_when_image_path_missing(tmp_path: Path):
    missing = tmp_path / "no-such-image.jpg"
    assert render_owl_pixels(20, 10, image_path=missing) is None


def test_renderer_fills_target_dimensions(tmp_path: Path):
    """The renderer fills the requested cell-grid exactly: source
    image is center-cropped to match the panel's visual aspect
    (not source aspect), then resized to fill. ``width`` ==
    target_w, ``height`` == target_h, exactly. No letterboxing,
    no aspect-preserving shrink that leaves empty bars."""
    a = render_owl_pixels(60, 30)
    b = render_owl_pixels(120, 30)
    assert a is not None and b is not None
    assert a["width"] == 60 and a["height"] == 30
    assert b["width"] == 120 and b["height"] == 30


def test_top_left_pixel_is_dark(monkeypatch):
    """Sanity — the source image has a dark backdrop, so the
    upper-left cell should be near-black, not white. Catches
    a class of "loaded wrong image" regressions."""
    matrix = render_owl_pixels(20, 10)
    assert matrix is not None
    _glyph, fg, bg = matrix["cells"][0][0]
    # Hex → int sum of RGB channels. Dark = low sum.
    def luminance(h: str) -> int:
        return int(h[1:3], 16) + int(h[3:5], 16) + int(h[5:7], 16)

    assert luminance(fg) < 200, (
        f"top-left cell unexpectedly bright: fg={fg} "
        "(loaded the wrong image?)"
    )
    assert luminance(bg) < 200


def test_renderer_returns_none_without_pillow(monkeypatch):
    """If Pillow is unavailable the renderer must short-circuit
    so the TUI falls back to ASCII art instead of crashing the
    banner build."""
    import sys

    # Stash and remove PIL — re-import the module so the
    # ``try: from PIL import Image`` block trips ImportError.
    monkeypatch.setitem(sys.modules, "PIL", None)
    assert render_owl_pixels(20, 10) is None


def test_only_quadrant_glyphs_appear_in_output():
    """The renderer's glyph set is fixed (the 16 quadrant block
    chars plus space and full block). Anything else means the
    encoder produced a glyph outside its lookup table — likely
    a regression in the bit-pattern → glyph mapping."""
    matrix = render_owl_pixels(30, 15)
    assert matrix is not None
    allowed = set(" ▗▖▄▝▐▞▟▘▚▌▙▀▜▛█")
    found = set()
    for row in matrix["cells"]:
        for cell in row:
            found.add(cell[0])
    extras = found - allowed
    assert not extras, f"unexpected glyphs in output: {extras!r}"


def test_flat_region_renders_as_solid_block():
    """A uniform 2×2 source region should encode as ``█`` with
    fg == bg (the flat-region shortcut), not as a quadrant
    glyph with two different colors. This preserves the soft
    look of large gradient areas."""
    from athena.tui_gateway.owl_image import _quadrant_cell

    flat = (40, 60, 80)
    glyph, fg, bg = _quadrant_cell(flat, flat, flat, flat)
    assert glyph == "█"
    assert fg == bg


def test_quadrant_pattern_high_contrast_diagonal():
    """Two bright pixels diagonal (TL + BR) on a dark background
    should produce ``▚`` — the diagonal quadrant glyph. Pins
    the bit-pattern → glyph lookup against accidental shuffles."""
    from athena.tui_gateway.owl_image import _quadrant_cell

    bright = (250, 250, 250)
    dark = (10, 10, 10)
    glyph, _fg, _bg = _quadrant_cell(bright, dark, dark, bright)
    assert glyph == "▚"


def test_banner_event_carries_pixels_field():
    """The wired path: build_banner() invokes the renderer and
    populates owl_pixels on the BannerEvent."""
    from athena.config import Config
    from athena.tui_gateway.banner_data import build_banner

    banner = build_banner(model="m", cwd=Path("/tmp"), cfg=Config())
    assert banner.owl_pixels is not None
    assert "cells" in banner.owl_pixels
    assert banner.owl_pixels["width"] > 0
    assert banner.owl_pixels["height"] > 0
