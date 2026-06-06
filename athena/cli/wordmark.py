"""``athena wordmark gallery`` — preview the ATHENA wordmark in
several figlet fonts so you can pick a favorite visually.

Six fonts curated to cover the design space:

  ansi_shadow    — current default; 6-row block with shadow corners
  ansi_regular   — 6-row clean blocks, no shadow rails
  cyberlarge     — 3-row angular tech aesthetic
  electronic     — pixelated LCD / synthwave digital
  doom           — 6-row heavy slabs, imposing
  slant          — 5-row italicized blocks, motion / urgency

Each font renders with the active palette's gradient applied per
letter (left-to-right rainbow). Static one-shot output — animation
lives in the TUI, not the CLI.

Usage:
  athena wordmark gallery
  athena wordmark gallery --font cyberlarge       # just one
  athena wordmark gallery --text "OWLBOY"         # any text
  athena wordmark gallery --list-fonts            # show every available
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, cast

from .. import ui

# Curated list — kept short on purpose. We don't want to dump 100
# fonts on the user; these are the ones I think actually look good
# for a brand wordmark in a TUI.
_GALLERY_FONTS: tuple[str, ...] = (
    "ansi_shadow",
    "ansi_regular",
    "cyberlarge",
    "electronic",
    "doom",
    "slant",
)


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    s = h.lstrip("#")
    if len(s) != 6:
        return (255, 255, 255)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def _ansi_fg(rgb: tuple[int, int, int]) -> str:
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


_RESET = "\033[0m"
_BOLD = "\033[1m"


def _render_with_gradient(
    rendered: str,
    *,
    gradient: list[str],
    letters_in_text: int,
) -> str:
    """Apply per-letter coloring to a figlet-rendered string.

    Strategy: walk each row and split on whitespace boundaries to
    isolate each letter's columns. Color them in palette-gradient
    order, wrapping if the text has more letters than gradient
    stops.

    Figlet output usually pads letters with single-column gaps so
    naively splitting on " " over-segments. We use whitespace-only
    boundary detection per character column to find letter blocks.
    """
    if not gradient:
        return rendered
    if letters_in_text <= 0:
        return rendered

    rows = rendered.split("\n")
    if not rows:
        return rendered

    # Find vertical bands that contain at least one non-space char
    # in any row — these are the letter columns. Whitespace columns
    # in EVERY row are gaps between letters.
    width = max(len(r) for r in rows)
    col_is_letter: list[bool] = []
    for c in range(width):
        any_nonspace = any(c < len(r) and not r[c].isspace() and r[c] != " " for r in rows)
        col_is_letter.append(any_nonspace)

    # Group consecutive letter columns into bands. Bands separated
    # by 1+ all-whitespace columns belong to different letters.
    bands: list[tuple[int, int]] = []
    cur_start: int | None = None
    for c, is_letter in enumerate(col_is_letter):
        if is_letter and cur_start is None:
            cur_start = c
        elif not is_letter and cur_start is not None:
            bands.append((cur_start, c))
            cur_start = None
    if cur_start is not None:
        bands.append((cur_start, width))

    # Assign each band a color. If we got fewer/more bands than
    # letters_in_text (figlet sometimes merges or splits), just walk
    # bands and cycle the gradient.
    out_rows: list[str] = []
    for row_text in rows:
        out = ""
        cursor = 0
        for band_idx, (start, end) in enumerate(bands):
            # Spaces before this band, render plain
            if cursor < start:
                out += row_text[cursor:start] if start <= len(row_text) else " " * (start - cursor)
            # The band itself, colored
            color = gradient[band_idx % len(gradient)]
            rgb = _hex_to_rgb(color)
            band_text = row_text[start:end] if start < len(row_text) else " " * (end - start)
            # Pad if row is short
            if start < len(row_text) and end > len(row_text):
                band_text = row_text[start:] + " " * (end - len(row_text))
            out += f"{_BOLD}{_ansi_fg(rgb)}{band_text}{_RESET}"
            cursor = end
        # Trailing chars after the last band
        if cursor < len(row_text):
            out += row_text[cursor:]
        out_rows.append(out)
    return "\n".join(out_rows)


def _figlet(text: str, font: str) -> str | None:
    """Render ``text`` in ``font`` using pyfiglet. Returns None if
    pyfiglet not installed or font not available."""
    try:
        import pyfiglet
    except ImportError:
        return None
    try:
        return cast(str, pyfiglet.figlet_format(text, font=font)).rstrip("\n")
    except Exception:  # noqa: BLE001 — bad font name etc
        return None


def _cmd_gallery(args: argparse.Namespace) -> int:
    text = args.text or "ATHENA"
    palette = ui.theme()
    gradient = (
        list(palette.gradient)
        if palette.gradient
        else [
            palette.accent,
            palette.primary,
            palette.primary_dim,
        ]
    )

    fonts = [args.font] if args.font else list(_GALLERY_FONTS)
    n_letters = len(text)
    any_rendered = False

    sys.stdout.write(f"{_BOLD}wordmark gallery — text={text!r}  theme={palette.name}{_RESET}\n\n")

    for i, font in enumerate(fonts):
        rendered = _figlet(text, font)
        if rendered is None:
            sys.stderr.write(f"  [skipped: {font} not available]\n")
            continue
        any_rendered = True
        # Header
        sys.stdout.write(f"{_BOLD}{_ansi_fg((180, 180, 180))}── {font} ──{_RESET}\n")
        colored = _render_with_gradient(
            rendered,
            gradient=gradient,
            letters_in_text=n_letters,
        )
        sys.stdout.write(colored)
        sys.stdout.write("\n")
        if i < len(fonts) - 1:
            sys.stdout.write("\n")

    sys.stdout.write("\n")
    if not any_rendered:
        sys.stderr.write("no fonts rendered. Install pyfiglet:\n  pip install pyfiglet\n")
        return 1

    sys.stdout.write(
        f"{_ansi_fg((150, 150, 150))}"
        f"pick a favorite, then set athena/_tui_bundle wordmark to "
        f"that font (see ui-tui/src/components/Wordmark.tsx).{_RESET}\n"
    )
    return 0


def _cmd_list_fonts(args: argparse.Namespace) -> int:
    """Dump every available pyfiglet font name — useful when looking
    beyond the curated gallery."""
    try:
        import pyfiglet
    except ImportError:
        sys.stderr.write("pyfiglet not installed: pip install pyfiglet\n")
        return 1
    # pyfiglet ships no type stubs; getFonts() is an untyped classmethod.
    raw_fonts = pyfiglet.FigletFont.getFonts()  # type: ignore[no-untyped-call,unused-ignore]
    fonts = sorted(cast("list[str]", raw_fonts))
    sys.stdout.write(f"{len(fonts)} available fonts:\n")
    for f in fonts:
        sys.stdout.write(f"  {f}\n")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="athena wordmark",
        description="Preview wordmark fonts.",
    )
    sub = ap.add_subparsers(dest="action")

    g = sub.add_parser("gallery", help="Render a curated set of fonts.")
    g.add_argument("--font", help="Render only this font.")
    g.add_argument(
        "--text",
        default="ATHENA",
        help="Text to render (default: ATHENA).",
    )
    g.set_defaults(func=_cmd_gallery)

    lf = sub.add_parser(
        "list-fonts",
        help="Print every pyfiglet font name (large list).",
    )
    lf.set_defaults(func=_cmd_list_fonts)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        # No subcommand → default to gallery
        args.font = None
        args.text = "ATHENA"
        return _cmd_gallery(args)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
