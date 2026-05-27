"""``athena image-demo [PATH]`` — verify terminal graphics protocol support.

Detects the terminal's image-protocol capabilities, picks the best one,
and emits the supplied PNG (default: the bundled wordmark) inline. Lets
the user confirm Sixel / Kitty / iTerm2 actually works on their setup
before any larger UI integration depends on it.

Usage:
  athena image-demo                       # show wordmark via best protocol
  athena image-demo /path/to/picture.png  # show a custom image
  athena image-demo --diag                # report caps without emitting
  athena image-demo --force sixel         # try a specific protocol
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..tui_gateway.image_protocols import encode_for_terminal
from ..tui_gateway.terminal_caps import detect_caps, is_a_tty


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="athena image-demo",
        description=(
            "Detect this terminal's image-protocol support and render "
            "the bundled wordmark (or a path you supply) inline."
        ),
    )
    ap.add_argument(
        "path", nargs="?", default=None,
        help="Image path to render (default: athena/_wordmark.png)",
    )
    ap.add_argument(
        "--diag", action="store_true",
        help="Print capability report only; don't emit any image data.",
    )
    ap.add_argument(
        "--force", choices=("kitty", "iterm2", "sixel"),
        help="Override capability detection and force a specific protocol.",
    )
    args = ap.parse_args(argv)

    caps = detect_caps()

    # Capability report — always shown so user sees what we detected.
    sys.stderr.write(f"terminal:  {caps.terminal_id}\n")
    sys.stderr.write(f"kitty:     {caps.kitty}\n")
    sys.stderr.write(f"iterm2:    {caps.iterm2}\n")
    sys.stderr.write(f"sixel:     {caps.sixel}\n")
    sys.stderr.write(f"truecolor: {caps.truecolor}\n")

    protocol = args.force or caps.best_image_protocol()
    sys.stderr.write(f"protocol:  {protocol}\n")

    if args.diag:
        return 0

    if protocol == "none":
        sys.stderr.write(
            "\nNo image protocol detected. If you're on a terminal that "
            "supports Sixel but isn't detected (xterm with --enable-sixel, "
            "or a less-common variant), retry with:\n"
            "  ATHENA_FORCE_SIXEL=1 athena image-demo\n"
            "or explicitly:\n"
            "  athena image-demo --force sixel\n"
        )
        return 1

    # Resolve image path. Default → bundled wordmark.
    if args.path:
        img_path = Path(args.path).expanduser().resolve()
    else:
        # Try the project-local bundled wordmark first; fall back to
        # an error if it's not there.
        candidates = [
            Path(__file__).resolve().parent.parent / "_wordmark.png",
            Path.cwd() / "athena" / "_wordmark.png",
        ]
        img_path = next((p for p in candidates if p.exists()), None)  # type: ignore[assignment]
        if img_path is None:
            sys.stderr.write(
                "could not find athena/_wordmark.png; pass a path explicitly\n"
            )
            return 2

    if not img_path.exists():
        sys.stderr.write(f"file not found: {img_path}\n")
        return 2

    try:
        from PIL import Image
    except ImportError:
        sys.stderr.write(
            "Pillow is required: pip install pillow\n"
        )
        return 3

    try:
        img = Image.open(img_path).convert("RGB")
    except OSError as e:
        sys.stderr.write(f"could not load image: {e}\n")
        return 2

    sys.stderr.write(f"image:     {img_path} ({img.size[0]}×{img.size[1]})\n")
    sys.stderr.write("\n")
    sys.stderr.flush()

    # Encode + write to stdout. The terminal renders it inline at the
    # current cursor position; the cursor then advances past the image.
    encoded = encode_for_terminal(img, protocol)
    if not encoded:
        sys.stderr.write(f"unknown protocol: {protocol}\n")
        return 4

    if not is_a_tty():
        sys.stderr.write(
            "stdout is not a TTY — escape sequences would be written as "
            "garbage. Run this command directly in your terminal.\n"
        )
        return 5

    sys.stdout.write(encoded)
    sys.stdout.write("\n")
    sys.stdout.flush()
    sys.stderr.write(f"\nemitted {len(encoded)} bytes via {protocol}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
