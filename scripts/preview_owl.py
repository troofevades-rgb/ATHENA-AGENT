"""Render the current owl matrix to a PNG that faithfully shows
what the terminal will paint cell-by-cell. Lets us "see" the
ship target without spawning the Ink TUI.

Each terminal cell is drawn as a 16×16 px tile. Quadrants are
rendered as four 8×8 subcells filled with FG or BG per the
glyph's pattern; solid blocks are filled with one color; spaces
are filled with the BG.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

from athena.tui_gateway.owl_image import render_owl_pixels

CELL = 16  # pixels per terminal cell in the preview
HALF = CELL // 2

# Bit positions per quadrant glyph: TL=3, TR=2, BL=1, BR=0
_GLYPH_TO_BITS = {
    " ": 0b0000,
    "▗": 0b0001,
    "▖": 0b0010,
    "▄": 0b0011,
    "▝": 0b0100,
    "▐": 0b0101,
    "▞": 0b0110,
    "▟": 0b0111,
    "▘": 0b1000,
    "▚": 0b1001,
    "▌": 0b1010,
    "▙": 0b1011,
    "▀": 0b1100,
    "▜": 0b1101,
    "▛": 0b1110,
    "█": 0b1111,
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def render_preview(out_path: Path, target_w: int, target_h: int) -> None:
    matrix = render_owl_pixels(target_w, target_h)
    if matrix is None:
        print("ERROR: render_owl_pixels returned None")
        sys.exit(1)
    w_cells = matrix["width"]
    h_cells = matrix["height"]
    img = Image.new("RGB", (w_cells * CELL, h_cells * CELL), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    for y, row in enumerate(matrix["cells"]):
        for x, (glyph, fg_hex, bg_hex) in enumerate(row):
            fg = _hex_to_rgb(fg_hex)
            bg = _hex_to_rgb(bg_hex)
            x0, y0 = x * CELL, y * CELL
            # Fill the whole cell with BG first.
            draw.rectangle(
                [x0, y0, x0 + CELL - 1, y0 + CELL - 1], fill=bg
            )
            bits = _GLYPH_TO_BITS.get(glyph, 0)
            # Then paint FG over the lit subcells.
            if bits & 0b1000:  # TL
                draw.rectangle(
                    [x0, y0, x0 + HALF - 1, y0 + HALF - 1], fill=fg
                )
            if bits & 0b0100:  # TR
                draw.rectangle(
                    [x0 + HALF, y0, x0 + CELL - 1, y0 + HALF - 1], fill=fg
                )
            if bits & 0b0010:  # BL
                draw.rectangle(
                    [x0, y0 + HALF, x0 + HALF - 1, y0 + CELL - 1], fill=fg
                )
            if bits & 0b0001:  # BR
                draw.rectangle(
                    [x0 + HALF, y0 + HALF, x0 + CELL - 1, y0 + CELL - 1],
                    fill=fg,
                )
    img.save(out_path)
    print(f"saved {out_path} ({w_cells}x{h_cells} cells → {img.size} px)")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/owl_preview.png")
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 48
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    render_preview(out, w, h)
