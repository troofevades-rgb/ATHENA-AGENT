"""``athena theme {list,preview}`` — inspect TUI color palettes.

Two subcommands:

  list     — Names + descriptions of every registered theme.
  preview  — Render a swatch block for each theme (or just one)
             so you can compare palettes visually without launching
             the full TUI.

Uses raw truecolor ANSI escapes so it works regardless of whether
the Ink TUI is in front. The swatch is intentionally compact
(~6 rows per theme) so several themes fit on one screen.
"""

from __future__ import annotations

import argparse
import sys

from .. import ui


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` to (r, g, b). Tolerant of missing leading ``#``."""
    s = h.lstrip("#")
    if len(s) != 6:
        return (255, 255, 255)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def _ansi_bg(rgb: tuple[int, int, int]) -> str:
    return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _ansi_fg(rgb: tuple[int, int, int]) -> str:
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


_RESET = "\033[0m"
_BOLD = "\033[1m"


def _swatch(rgb: tuple[int, int, int], width: int = 6) -> str:
    """A small solid block of color, ``width`` cells wide."""
    return f"{_ansi_bg(rgb)}{' ' * width}{_RESET}"


def _format_theme_preview(theme: ui.Theme) -> str:
    """One theme rendered as: name/description + swatches + gradient."""
    lines: list[str] = []
    # Header line
    primary_rgb = _hex_to_rgb(theme.primary)
    lines.append(
        f"{_BOLD}{_ansi_fg(primary_rgb)}{theme.name}{_RESET}"
        f"  {_ansi_fg(_hex_to_rgb(theme.primary_dim))}{theme.description}{_RESET}"
    )

    # Named swatches row — label below each color block
    fields = [
        ("primary", theme.primary),
        ("dim", theme.primary_dim),
        ("faint", theme.primary_faint),
        ("accent", theme.accent),
        ("acc.dim", theme.accent_dim),
    ]
    swatch_row = "  " + "  ".join(
        _swatch(_hex_to_rgb(hex_)) for _, hex_ in fields
    )
    label_row = "  " + "  ".join(
        f"{_ansi_fg(_hex_to_rgb(hex_))}{name:<6}{_RESET}"
        for name, hex_ in fields
    )
    lines.append(swatch_row)
    lines.append(label_row)

    # Gradient strip — useful for the wordmark / banner top-to-bottom
    # fade. Render each step as 4 cells of bg so you can see the
    # progression.
    if theme.gradient:
        grad = "  " + "".join(
            _swatch(_hex_to_rgb(c), width=4) for c in theme.gradient
        )
        lines.append(grad)
        lines.append(
            "  " + _ansi_fg(_hex_to_rgb(theme.primary_dim))
            + f"gradient ({len(theme.gradient)} stops)" + _RESET,
        )

    return "\n".join(lines)


def _cmd_list(args: argparse.Namespace) -> int:
    """``athena theme list`` — just the names + descriptions."""
    width = max(len(t.name) for t in ui.list_themes())
    for t in ui.list_themes():
        marker = "*" if t.name == ui.theme().name else " "
        sys.stdout.write(f"{marker} {t.name:<{width}}  {t.description}\n")
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    """``athena theme preview [NAME]`` — render swatch block(s)."""
    if args.name:
        if args.name not in ui.THEMES:
            sys.stderr.write(
                f"unknown theme: {args.name!r}. "
                f"Available: {', '.join(sorted(ui.THEMES))}\n",
            )
            return 1
        themes = [ui.THEMES[args.name]]
    else:
        themes = ui.list_themes()

    for i, theme in enumerate(themes):
        sys.stdout.write(_format_theme_preview(theme))
        sys.stdout.write("\n")
        if i < len(themes) - 1:
            # Blank line between themes for visual separation
            sys.stdout.write("\n")
    sys.stdout.write("\n")
    sys.stdout.write(
        f"Active theme: {_BOLD}{ui.theme().name}{_RESET}  "
        f"(switch in TUI with /theme set NAME or in config.toml)\n"
    )
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="athena theme",
        description="Inspect registered TUI color palettes.",
    )
    sub = ap.add_subparsers(dest="action")

    sub_list = sub.add_parser("list", help="Names + descriptions only.")
    sub_list.set_defaults(func=_cmd_list)

    sub_preview = sub.add_parser(
        "preview",
        help="Render color swatches for one or every theme.",
    )
    sub_preview.add_argument(
        "name", nargs="?",
        help="Theme name to preview (default: all registered themes).",
    )
    sub_preview.set_defaults(func=_cmd_preview)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        # No subcommand → default to preview (most useful)
        args.name = None
        return _cmd_preview(args)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
