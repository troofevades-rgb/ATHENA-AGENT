"""Render the bundled owl photo into a terminal-friendly pixel
matrix the Ink TUI can paint with quadrant block characters.

Rendering model
---------------

Quadrant blocks: each terminal cell holds a glyph encoding a 2×2
source-pixel grid (TL TR / BL BR). 16 patterns:

  pattern (TL,TR,BL,BR) → glyph
    0000 → ' '         0001 → '▗'
    0010 → '▖'         0011 → '▄'
    0100 → '▝'         0101 → '▐'
    0110 → '▞'         0111 → '▟'
    1000 → '▘'         1001 → '▚'
    1010 → '▌'         1011 → '▙'
    1100 → '▀'         1101 → '▜'
    1110 → '▛'         1111 → '█'

Each cell has a foreground (the "lit" pixels) and a background
(the "unlit" pixels). For each 2×2 source region we split the
four pixels into two clusters by luminance — the brighter two
form FG, the darker two form BG — then look up the glyph by the
4-bit pattern. Net result: 4 source pixels per cell vs 2 with
half-blocks; horizontal detail doubles.

When a region is uniform (low luminance spread) we shortcut to
a solid ``█`` with the average color so flat areas don't get
fake quadrant edges.

Output shape
------------

``render_owl_pixels(target_w, target_h)`` returns::

    {
        "width":  <int>,          # output cells per row
        "height": <int>,           # output rows
        "cells":  [
            [ ["<glyph>", "#FG", "#BG"], ... ],
            ...
        ],
    }

Wire size stays compact: one 3-tuple per cell. A 48×24 render
serializes to ~1,150 tuples ≈ 18 KB JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Sequence

_IMAGE_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "_owl_image.jpg"
)

# Lookup table mapping a 4-bit (TL,TR,BL,BR) pattern to its
# corresponding Unicode quadrant glyph. Indexed: bit 3=TL,
# bit 2=TR, bit 1=BL, bit 0=BR.
_QUADRANT_GLYPHS: Final[tuple[str, ...]] = (
    " ",   # 0000
    "▗",   # 0001
    "▖",   # 0010
    "▄",   # 0011
    "▝",   # 0100
    "▐",   # 0101
    "▞",   # 0110
    "▟",   # 0111
    "▘",   # 1000
    "▚",   # 1001
    "▌",   # 1010
    "▙",   # 1011
    "▀",   # 1100
    "▜",   # 1101
    "▛",   # 1110
    "█",   # 1111
)

# Below this luminance spread we treat the 2×2 region as flat
# and emit a solid block instead of pretending there's an edge.
# Tuned by eye on the cyber-owl image; lower = more quadrant
# noise in dark areas, higher = blockier render of soft regions.
_FLAT_SPREAD_THRESHOLD = 18  # tightened: more cells preserve edge detail


def render_owl_pixels(
    target_w: int,
    target_h: int,
    *,
    image_path: Path | None = None,
) -> dict[str, Any] | None:
    """Render the bundled image at ``target_w × target_h`` cells
    using quadrant blocks (4 source pixels per cell). Returns
    ``None`` when Pillow isn't available or the file is missing
    — callers fall back to ASCII rendering."""
    if target_w <= 0 or target_h <= 0:
        return None

    try:
        from PIL import Image
    except ImportError:
        return None

    path = image_path or _IMAGE_PATH
    if not path.exists():
        return None

    try:
        img = Image.open(path).convert("RGB")
    except OSError:
        return None

    # Preprocess at source resolution so edges survive resize.
    # Tuned for the cyber-owl source: high contrast to crisp the
    # eyes + perch glow against shadow; saturation boost to keep
    # the cyan from washing out at small cell counts; two-stage
    # sharpen (UnsharpMask for detail + Pillow SHARPEN convolution
    # for edges) to compensate for the 8x downsample blur.
    try:
        from PIL import ImageEnhance, ImageFilter

        img = ImageEnhance.Contrast(img).enhance(1.35)
        img = ImageEnhance.Color(img).enhance(1.25)
        img = img.filter(
            ImageFilter.UnsharpMask(radius=2.2, percent=140, threshold=1)
        )
        img = img.filter(ImageFilter.SHARPEN)
    except ImportError:
        pass

    # Quadrants encode 2 source pixels in each of width AND
    # height, so the "image" we resize to is target_w*2 wide ×
    # target_h*2 tall (in source pixels).
    pixel_w_target = target_w * 2
    pixel_h_target = target_h * 2
    # Crop source to match the panel's VISUAL aspect (W/H in
    # terminal units), not the source-pixel aspect. Terminal
    # cells render about 2× taller than wide, so for ``target_w``
    # cells × ``target_h`` cells, the visual aspect on screen is
    # ``target_w / (target_h * 2)``. Cropping the source to that
    # ratio means a 64×32-cell panel (1.0 visual) only needs a
    # tiny crop on the near-square source (0.9 visual) — head
    # and cube pedestal both survive.
    visual_aspect = target_w / (target_h * 2)
    img = _aspect_crop(img, visual_aspect)
    # After the crop, source has the matching visual aspect so
    # the resize fills the entire pixel target.
    out_pix_w = pixel_w_target
    out_pix_h = pixel_h_target
    if out_pix_w % 2:
        out_pix_w -= 1
    if out_pix_h % 2:
        out_pix_h -= 1
    if out_pix_w < 2 or out_pix_h < 2:
        return None

    resized = img.resize((out_pix_w, out_pix_h), Image.Resampling.LANCZOS)
    px = resized.load()

    out_cells_w = out_pix_w // 2
    out_cells_h = out_pix_h // 2
    cells_matrix: list[list[list[str]]] = []
    for cy in range(out_cells_h):
        row: list[list[str]] = []
        py = cy * 2
        for cx in range(out_cells_w):
            px_x = cx * 2
            tl = px[px_x, py]
            tr = px[px_x + 1, py]
            bl = px[px_x, py + 1]
            br = px[px_x + 1, py + 1]
            row.append(_quadrant_cell(tl, tr, bl, br))
        cells_matrix.append(row)

    return {
        "width": out_cells_w,
        "height": out_cells_h,
        "cells": cells_matrix,
    }


# Pixel = tuple of ints (R, G, B) returned by Pillow.
Pixel = Sequence[int]


def _quadrant_cell(
    tl: Pixel, tr: Pixel, bl: Pixel, br: Pixel
) -> list[str]:
    """Compute ``[glyph, fg_hex, bg_hex]`` for one 2×2 source
    region. Split the 4 pixels by median luminance into two
    clusters; brighter two become FG, darker two become BG.
    Flat regions (low spread) get a solid block instead."""
    pixels = [tl, tr, bl, br]
    lumas = [_luma(p) for p in pixels]
    lo, hi = min(lumas), max(lumas)
    if hi - lo < _FLAT_SPREAD_THRESHOLD:
        # Uniform region — solid block with the average color.
        avg = _avg(pixels)
        return ["█", _hex(avg), _hex(avg)]

    median = (lo + hi) / 2.0
    bg_pixels: list[Pixel] = []
    fg_pixels: list[Pixel] = []
    pattern = 0  # bit 3=TL, 2=TR, 1=BL, 0=BR
    for i, p in enumerate(pixels):
        if lumas[i] >= median:
            fg_pixels.append(p)
            # Bits: TL=3, TR=2, BL=1, BR=0.
            pattern |= 1 << (3 - i)
        else:
            bg_pixels.append(p)
    if not bg_pixels:  # degenerate — all above median
        bg_pixels = [pixels[lumas.index(lo)]]
    if not fg_pixels:
        fg_pixels = [pixels[lumas.index(hi)]]
    fg = _hex(_avg(fg_pixels))
    bg = _hex(_avg(bg_pixels))
    glyph = _QUADRANT_GLYPHS[pattern]
    return [glyph, fg, bg]


def _luma(p: Pixel) -> float:
    """ITU-R BT.601 luma — matches how the human eye weights
    color channels. R contributes most to perceived brightness,
    blue least."""
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def _avg(pixels: list[Pixel]) -> tuple[int, int, int]:
    if not pixels:
        return (0, 0, 0)
    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    return (r, g, b)


def _hex(rgb: Pixel) -> str:
    r, g, b = rgb[0], rgb[1], rgb[2]
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _aspect_crop(img: Any, target_aspect: float) -> Any:
    """Crop ``img`` to ``target_aspect`` (W/H ratio).

    For the cyber-owl photo, the subject is horizontally centered
    but vertically biased toward the upper-middle, with the glowing
    pedestal anchoring the bottom. So:

    - Horizontal trims are symmetric (subject is centered L/R).
    - Vertical trims are biased to remove empty sky from the top
      and preserve the pedestal at the bottom.

    Returns the image unchanged when the source already matches the
    target ratio (within a small tolerance).
    """
    src_w, src_h = img.size
    if src_h == 0:
        return img
    src_aspect = src_w / src_h
    if abs(src_aspect - target_aspect) < 0.01:
        return img
    if src_aspect > target_aspect:
        # Source too wide — trim left + right symmetrically.
        new_w = int(src_h * target_aspect)
        x = (src_w - new_w) // 2
        return img.crop((x, 0, x + new_w, src_h))
    # Source too tall — bias toward keeping the bottom (pedestal)
    # by taking only ~25% from the bottom and ~75% from the top
    # (which is empty background in the cyber-owl source).
    new_h = int(src_w / target_aspect)
    trim = src_h - new_h
    y_top = int(trim * 0.75)
    y_bot = y_top + new_h
    return img.crop((0, y_top, src_w, y_bot))
