"""Encoder tests for ``athena.tui_gateway.image_protocols``.

Zero coverage today. These encoders generate the DCS / OSC escape
sequences that the gateway dumps to the terminal to display the
wordmark / owl banner image. If they're wrong the user sees a
screen full of garbage.

We test the encoders against the OBSERVABLE wire format:

  - Kitty:  starts with ESC_G, ends with ESC\\, base64 payload,
            chunked when large.
  - iTerm2: starts with OSC 1337 ;File=..., ends with BEL.
  - Sixel:  starts with DCS Pq, ends with ST, has palette defs
            and only legal sixel chars.

We deliberately do not decode the image roundtrip to a pixel
comparison — that's a test of PIL, not of our encoder.
"""

from __future__ import annotations

import base64
import re

import pytest

PIL = pytest.importorskip("PIL.Image")  # skip if pillow not installed

from athena.tui_gateway.image_protocols import (  # noqa: E402
    encode_iterm2,
    encode_kitty,
    encode_sixel,
)


def _solid_image(size: tuple[int, int], color=(255, 0, 0)):
    """Make a small solid-color test image."""
    return PIL.new("RGB", size, color=color)


# ---------------------------------------------------------------------------
# Kitty graphics protocol
# ---------------------------------------------------------------------------


def test_kitty_output_starts_and_ends_with_dcs_markers() -> None:
    """Kitty wraps every chunk in ESC_G ... ESC\\ . Without the
    framing the terminal prints the payload as garbage text."""
    out = encode_kitty(_solid_image((10, 10)))
    assert out.startswith("\033_G"), (
        f"missing DCS opener; first 10 bytes={out[:10]!r}"
    )
    assert out.endswith("\033\\"), (
        f"missing DCS terminator; last 5 bytes={out[-5:]!r}"
    )


def test_kitty_first_chunk_declares_png_format_and_action() -> None:
    """Per the Kitty protocol spec, the first transmission carries
    ``a=T`` (transmit-and-display) and ``f=100`` (PNG). Subsequent
    chunks only carry ``m=...``."""
    out = encode_kitty(_solid_image((10, 10)))
    # First chunk is everything up to the first DCS terminator
    first_chunk = out.split("\033\\", 1)[0]
    assert "a=T" in first_chunk, "first chunk missing transmission action"
    assert "f=100" in first_chunk, "first chunk missing PNG format flag"


def test_kitty_chunks_large_payload_with_m_flag() -> None:
    """The encoder must split payloads larger than the per-chunk
    cap (4096) into multiple DCS sequences with ``m=1`` on every
    chunk except the last. Otherwise terminals may truncate."""
    # Make an image that produces a base64 payload > 4096 bytes.
    # 200x200 noise compresses poorly enough.
    import random
    random.seed(0)
    img = PIL.new("RGB", (200, 200))
    img.putdata([
        (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for _ in range(200 * 200)
    ])
    out = encode_kitty(img)
    # Multiple chunks
    chunks = out.split("\033_G")[1:]  # split-on-opener; first is empty
    assert len(chunks) >= 2, (
        f"large image not chunked; got {len(chunks)} chunks. "
        f"Output size={len(out)}"
    )
    # All but last carry m=1
    for c in chunks[:-1]:
        assert "m=1" in c, "non-final chunk missing m=1 (more-follows flag)"
    assert "m=0" in chunks[-1], "final chunk missing m=0"


def test_kitty_payload_is_valid_base64_png() -> None:
    """Concatenate all chunks' payloads, base64-decode, and verify
    the result is a real PNG (starts with the PNG magic). If the
    encoding gets a stray non-base64 character somewhere the terminal
    just shows nothing — silent failure."""
    out = encode_kitty(_solid_image((10, 10)))
    # Extract payload from each chunk: between the semicolon and the
    # ESC\\ terminator.
    payloads = []
    for chunk in out.split("\033_G")[1:]:
        body = chunk.split("\033\\", 1)[0]
        # body looks like "a=T,f=100,m=0;<base64>"
        _ctrl, _, b64 = body.partition(";")
        payloads.append(b64)
    full = "".join(payloads)
    decoded = base64.standard_b64decode(full)
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n", (
        f"payload is not a valid PNG; first bytes={decoded[:8]!r}"
    )


# ---------------------------------------------------------------------------
# iTerm2 inline images
# ---------------------------------------------------------------------------


def test_iterm2_output_uses_osc_1337_framing() -> None:
    """iTerm2 uses OSC 1337 ; ... BEL framing. The BEL (0x07)
    terminator is critical — iTerm doesn't accept ST here."""
    out = encode_iterm2(_solid_image((10, 10)))
    assert out.startswith("\033]1337;File="), (
        f"missing OSC 1337 opener; first 20 bytes={out[:20]!r}"
    )
    assert out.endswith("\007"), (
        f"missing BEL terminator; iTerm2 will hang waiting for it"
    )


def test_iterm2_name_is_base64_in_header() -> None:
    """The ``name=`` field is base64-encoded per spec. Some iTerm
    versions reject plain text. Decode and verify round-trip."""
    out = encode_iterm2(_solid_image((10, 10)), name="banner")
    m = re.search(r"name=([^;]+)", out)
    assert m, f"no name= field in output: {out[:80]!r}"
    decoded = base64.standard_b64decode(m.group(1)).decode("ascii")
    assert decoded == "banner"


def test_iterm2_size_field_matches_payload_length() -> None:
    """size=N must match the actual base64 payload length; iTerm uses
    it to gate the buffer it allocates."""
    out = encode_iterm2(_solid_image((10, 10)))
    m = re.search(r"size=(\d+):", out)
    assert m, f"no size= field; output={out[:120]!r}"
    declared = int(m.group(1))
    # Extract payload between ':' and BEL
    payload = out.split(":", 1)[1].rstrip("\007")
    assert declared == len(payload), (
        f"size={declared} but actual payload is {len(payload)} bytes"
    )


def test_iterm2_inline_flag_controls_display() -> None:
    """inline=1 → display in-place; inline=0 → just transmit. Both
    must be representable."""
    on = encode_iterm2(_solid_image((10, 10)), inline=True)
    off = encode_iterm2(_solid_image((10, 10)), inline=False)
    assert "inline=1" in on
    assert "inline=0" in off


# ---------------------------------------------------------------------------
# Sixel
# ---------------------------------------------------------------------------


_SIXEL_LEGAL_DATA_RANGE = set(chr(c) for c in range(0x3F, 0x7F))  # '?'..'~'


def test_sixel_output_wrapped_in_dcs_pq() -> None:
    """Sixel starts with DCS Pq (\\033Pq) and ends with ST (\\033\\).
    Without these the terminal prints the palette + bitmap as text."""
    out = encode_sixel(_solid_image((6, 6)))
    assert out.startswith("\033Pq"), (
        f"missing DCS Pq opener; first 10 bytes={out[:10]!r}"
    )
    assert out.endswith("\033\\"), (
        f"missing ST terminator; last 5 bytes={out[-5:]!r}"
    )


def test_sixel_includes_palette_definitions() -> None:
    """At least one ``#N;2;R;G;B`` palette entry. Without these the
    terminal has no colors to draw with."""
    out = encode_sixel(_solid_image((6, 6), color=(0, 200, 100)))
    # Palette format: #<num>;2;<r>;<g>;<b>
    assert re.search(r"#\d+;2;\d+;\d+;\d+", out), (
        f"no palette definitions found in sixel output"
    )


def test_sixel_data_chars_are_in_legal_range() -> None:
    """Sixel data characters are 0x3F ('?') through 0x7E ('~'). Any
    char outside that range in the data section breaks the protocol
    or gets rendered as text."""
    out = encode_sixel(_solid_image((12, 6)))
    # Strip header (DCS Pq + palette defs) and footer (ST). The
    # encoded data is what lies between the last '#N' palette ref
    # and ESC\\. Approximate: every char between ESC Pq and ESC\\
    # that isn't part of an escape sequence or palette/control
    # sigil must be in the sixel range.
    body = out[len("\033Pq"):-len("\033\\")]
    # Strip palette + RLE/color/control sigils that aren't data:
    # #N;2;R;G;B  → palette
    # #N           → color select
    # !Nc          → RLE
    # $            → carriage return
    # -            → line feed
    stripped = re.sub(r"#\d+(?:;2;\d+;\d+;\d+)?", "", body)
    stripped = re.sub(r"![0-9]+", "", stripped)
    stripped = stripped.replace("$", "").replace("-", "")
    illegal = [c for c in stripped if c not in _SIXEL_LEGAL_DATA_RANGE]
    assert not illegal, (
        f"sixel data contains {len(illegal)} illegal chars: "
        f"{illegal[:5]} (codepoints {[ord(c) for c in illegal[:5]]})"
    )


def test_sixel_solid_color_image_uses_rle() -> None:
    """A solid-color image is highly compressible. The encoder MUST
    emit RLE (``!Nc``) — without it the wire format balloons by
    ~4× and overflows the terminal's per-line buffer."""
    out = encode_sixel(_solid_image((100, 24), color=(255, 0, 0)))
    # RLE marker
    assert "!" in out, "no RLE markers found on a flat image — encoder regressed"


def test_sixel_handles_multiple_colors() -> None:
    """A multi-color image needs multiple palette entries AND
    multiple color-select directives in the data."""
    img = PIL.new("RGB", (12, 6))
    pixels = img.load()
    for x in range(12):
        for y in range(6):
            pixels[x, y] = (255, 0, 0) if x < 6 else (0, 255, 0)
    out = encode_sixel(img)
    # At least 2 palette entries
    palette_entries = re.findall(r"#\d+;2;", out)
    assert len(palette_entries) >= 2, (
        f"expected ≥2 palette entries for 2-color image; got {len(palette_entries)}"
    )
