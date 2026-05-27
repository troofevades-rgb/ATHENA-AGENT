"""Encode images to terminal escape sequences.

Three protocols, picked via ``terminal_caps.best_image_protocol()``:

  - **Kitty graphics protocol** — base64 PNG inside ``\\033_G...;\\033\\``
    DCS sequences. Simplest to encode (just base64 the bytes).
  - **iTerm2 inline images** — base64 PNG inside an OSC 1337 sequence.
    Same data shape as Kitty, different framing.
  - **Sixel** — bitmap pixels packed into a Six-by-N character grid.
    Most universal; most encoding work. We quantize the image to
    a ≤256-color palette, then emit standard ``\\033Pq`` sequences.

All encoders take a PIL ``Image`` and return a ``str`` ready to write
to stdout. None of them write directly — caller controls timing /
ordering / cursor position.
"""

from __future__ import annotations

import base64
import io
from typing import Any

# Sixel uses these glyphs (0x3F == '?'; 0x3F + 0..63 → '?' .. '~')
_SIXEL_BASE = 0x3F


def encode_kitty(image: Any) -> str:
    """Encode a PIL Image to the Kitty graphics protocol.

    Emits one chunked transmission so very large images don't blow
    the terminal's max-line buffer. ``a=T`` says "transmit and
    display in-place at the current cursor"; the image consumes
    cells matching its pixel size divided by the terminal cell
    size. Caller is responsible for placing the cursor first.
    """
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    payload = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    out: list[str] = []
    # 4096-byte chunks; intermediate chunks set ``m=1`` (more
    # follows), last chunk uses ``m=0``.
    CHUNK = 4096
    while payload:
        chunk = payload[:CHUNK]
        payload = payload[CHUNK:]
        more = 1 if payload else 0
        if not out:
            # First chunk carries the metadata: PNG format + display
            # + transmission action.
            ctrl = f"a=T,f=100,m={more}"
        else:
            ctrl = f"m={more}"
        out.append(f"\033_G{ctrl};{chunk}\033\\")
    return "".join(out)


def encode_iterm2(image: Any, *, name: str = "image", inline: bool = True) -> str:
    """Encode a PIL Image to the iTerm2 inline-image OSC 1337
    sequence. The whole payload is base64'd in a single block; iTerm
    doesn't need chunking like Kitty does."""
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    name_b64 = base64.standard_b64encode(name.encode("utf-8")).decode("ascii")
    inline_flag = "1" if inline else "0"
    return (
        f"\033]1337;File=name={name_b64};inline={inline_flag};"
        f"size={len(data)}:{data}\007"
    )


def encode_sixel(image: Any, *, max_colors: int = 256) -> str:
    """Encode a PIL Image to a Sixel escape sequence.

    Strategy:
      1. Quantize to ``max_colors`` palette so we have a small,
         enumerable color set.
      2. Emit palette definitions: ``#N;2;R;G;B`` (sixel "RGB100"
         scale — each channel 0..100 not 0..255).
      3. For each band of 6 rows of the image:
         For each palette index used in this band:
           Select that color (``#N``), then for each column emit
           one sixel char whose 6 bits indicate which of this
           band's 6 rows are this color.
           After each color pass, emit ``$`` (carriage return).
         After all colors in this band, emit ``-`` (line feed).

    The encoding is verbose but straightforward; libsixel would
    do it faster but we don't depend on it. For typical use cases
    (50-200 pixel wide wordmark, ~30 pixels tall) the output is
    a few KB.
    """
    from PIL import Image  # local import — caller already has PIL

    # 1. Quantize. ``Image.quantize`` uses a median-cut palette by
    # default and gives consistently good results for graphics.
    img = image.convert("RGB").quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
    palette = img.getpalette() or []
    used = sorted(set(img.getdata()))
    width, height = img.size

    out: list[str] = []
    # DCS Pq — enter sixel mode. Aspect ratio "9" + "1" defaults.
    out.append("\033Pq")

    # Palette definitions. RGB scale is 0..100 in sixel.
    for idx in used:
        r = palette[idx * 3] if idx * 3 + 2 < len(palette) else 0
        g = palette[idx * 3 + 1] if idx * 3 + 2 < len(palette) else 0
        b = palette[idx * 3 + 2] if idx * 3 + 2 < len(palette) else 0
        # Scale 0..255 → 0..100
        r100 = (r * 100 + 127) // 255
        g100 = (g * 100 + 127) // 255
        b100 = (b * 100 + 127) // 255
        out.append(f"#{idx};2;{r100};{g100};{b100}")

    # Build a fast row→pixel lookup. img.load() gives us O(1) access.
    pixels = img.load()

    # 3. Emit band by band.
    for band_y in range(0, height, 6):
        band_rows = min(6, height - band_y)
        # For each color used in this band, walk the band.
        # Pre-compute which (color, x) pairs have any pixels so we
        # don't emit color-passes for unused colors.
        colors_in_band: dict[int, list[int]] = {}
        for x in range(width):
            for dy in range(band_rows):
                p = pixels[x, band_y + dy]
                colors_in_band.setdefault(p, []).append(0)  # placeholder
                break  # we just need existence per color
        # That gave us only "is this color in this band at all".
        # Actual bit packing happens below.
        band_colors = sorted(colors_in_band.keys())

        for ci, color in enumerate(band_colors):
            out.append(f"#{color}")
            # Walk x; emit one sixel char per column.
            # RLE: collect runs of identical chars and emit ``!Nc``
            # for run length N. Massive size reduction on flat areas.
            prev_char: int | None = None
            run = 0
            row_chars: list[str] = []
            for x in range(width):
                bits = 0
                for dy in range(band_rows):
                    if pixels[x, band_y + dy] == color:
                        bits |= 1 << dy
                ch = _SIXEL_BASE + bits
                if ch == prev_char:
                    run += 1
                else:
                    if prev_char is not None:
                        row_chars.append(_emit_run(prev_char, run))
                    prev_char = ch
                    run = 1
            if prev_char is not None:
                row_chars.append(_emit_run(prev_char, run))
            out.append("".join(row_chars))
            if ci < len(band_colors) - 1:
                # Carriage return: start of band again for next color.
                out.append("$")
        # Next band.
        if band_y + 6 < height:
            out.append("-")

    out.append("\033\\")
    return "".join(out)


def _emit_run(ch: int, run: int) -> str:
    """Emit a sixel character with RLE if profitable.

    ``!Nc`` runs save bytes when N >= 4 (the form ``!Nc`` is 3 chars
    plus the digits, so a run needs to be at least 4 to beat raw).
    For typical images with large flat areas this drops output size
    by 80%+.
    """
    glyph = chr(ch)
    if run >= 4:
        return f"!{run}{glyph}"
    return glyph * run


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def encode_for_terminal(image: Any, protocol: str) -> str:
    """Pick the right encoder for the named protocol.

    ``protocol`` is the string returned by
    :meth:`TerminalCaps.best_image_protocol` —
    ``"kitty"`` | ``"iterm2"`` | ``"sixel"`` | ``"none"``.

    Returns empty string for ``"none"`` so callers can write
    unconditionally.
    """
    if protocol == "kitty":
        return encode_kitty(image)
    if protocol == "iterm2":
        return encode_iterm2(image)
    if protocol == "sixel":
        return encode_sixel(image)
    return ""
