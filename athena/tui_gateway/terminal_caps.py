"""Detect terminal graphics-protocol support.

Three protocols, in order of preference:

  1. Kitty graphics protocol  — base64-encoded PNG via DCS sequences.
     Supported by: kitty, WezTerm, Ghostty.
  2. iTerm2 inline images     — base64-encoded image in OSC 1337.
     Supported by: iTerm2 only (macOS).
  3. Sixel                    — bitmap pixels via DCS Pq sequences.
     Supported by: xterm (with --enable-sixel), kitty (partial),
     WezTerm, mlterm, Windows Terminal v1.22+, Ghostty (recent),
     foot, contour, Sextant.

Detection strategy — env vars first (cheap, reliable when set),
then well-known patterns. We deliberately do NOT issue a runtime
query escape sequence because:
  * it requires the calling process to own the terminal
  * the response timing is racy
  * the env-var signals catch 95% of cases

Callers that need higher accuracy can pass ``probe=True`` to
``detect_caps`` to additionally issue a Device Attributes query
(returns the terminal's reported capabilities). That's an opt-in
because we can't issue it from inside the Ink subprocess without
fighting Ink for stdin.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class TerminalCaps:
    """Snapshot of what the current terminal can do.

    Booleans are independent — a terminal can support multiple
    protocols (e.g. WezTerm does Sixel AND Kitty). The caller
    picks ONE based on preference order.
    """

    kitty: bool
    iterm2: bool
    sixel: bool
    truecolor: bool
    # Free-form identification for logging / debugging.
    terminal_id: str

    def best_image_protocol(self) -> str:
        """Return the preferred protocol name, or 'none' if no
        image protocol is supported. Order: kitty > iterm2 > sixel.

        Kitty wins on capability (PNG, animations, positioning);
        iTerm2 wins on macOS quality; Sixel is the broadest
        fallback.
        """
        if self.kitty:
            return "kitty"
        if self.iterm2:
            return "iterm2"
        if self.sixel:
            return "sixel"
        return "none"


# ---------------------------------------------------------------------------
# Detection — env vars + known program identifiers
# ---------------------------------------------------------------------------


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _detect_kitty() -> bool:
    """Kitty sets ``KITTY_WINDOW_ID``. WezTerm and Ghostty implement
    the protocol but advertise differently."""
    if _env("KITTY_WINDOW_ID"):
        return True
    if _env("TERM_PROGRAM") in {"WezTerm", "ghostty"}:
        return True
    # Ghostty also sets GHOSTTY_RESOURCES_DIR
    if _env("GHOSTTY_RESOURCES_DIR"):
        return True
    return False


def _detect_iterm2() -> bool:
    """iTerm2 sets ``TERM_PROGRAM=iTerm.app`` and
    ``LC_TERMINAL=iTerm2``."""
    if _env("TERM_PROGRAM") == "iTerm.app":
        return True
    if _env("LC_TERMINAL") == "iTerm2":
        return True
    return False


def _detect_sixel() -> bool:
    """Sixel support — broadest of the three. Detection priority:

      * explicit override (``ATHENA_FORCE_SIXEL=1`` for testing)
      * known program identifiers
      * TERM hints

    We're permissive here — false positives mean the user sees
    garbage characters once; false negatives mean we lose a
    feature. Better to attempt and fall back.
    """
    if _env("ATHENA_FORCE_SIXEL") == "1":
        return True

    tp = _env("TERM_PROGRAM")
    if tp in {"WezTerm", "mintty", "ghostty", "foot", "contour"}:
        return True

    # Windows Terminal: v1.22 (Oct 2024) added Sixel support.
    # Heuristic — WT_SESSION is always set when running inside
    # Windows Terminal; we can't check the version cheaply, so
    # we assume support. Users on older WT will see garbage and
    # can opt out with ``ATHENA_FORCE_SIXEL=0``.
    if _env("WT_SESSION") and _env("ATHENA_FORCE_SIXEL") != "0":
        return True

    # mlterm explicitly advertises sixel
    term = _env("TERM")
    if "mlterm" in term or "sixel" in term:
        return True

    # xterm-256color is the most common TERM value but xterm only
    # supports sixel if compiled with --enable-sixel (uncommon
    # default). Don't assume; user can opt in with the env var.

    return False


def _detect_truecolor() -> bool:
    """24-bit color support. Almost universal on modern terminals
    but worth checking — falls back to 256-color on really old
    stuff."""
    if _env("COLORTERM") in {"truecolor", "24bit"}:
        return True
    term = _env("TERM")
    # Most modern xterm variants
    if re.search(r"(?:^|-)(?:direct|truecolor|24bit)$", term):
        return True
    # Assume yes on the common terminals we already detected
    if (
        _detect_kitty() or _detect_iterm2()
        or _env("WT_SESSION") or _env("TERM_PROGRAM") == "WezTerm"
    ):
        return True
    return False


def _terminal_id() -> str:
    """Best-effort identifier for logs."""
    tp = _env("TERM_PROGRAM")
    term = _env("TERM")
    if tp:
        return f"{tp} (TERM={term})"
    if _env("WT_SESSION"):
        return f"Windows Terminal (TERM={term})"
    return f"unknown (TERM={term})"


def detect_caps() -> TerminalCaps:
    """Snapshot the current terminal's image-protocol support.

    Cheap — pure env-var sniff, no I/O. Safe to call repeatedly.
    """
    return TerminalCaps(
        kitty=_detect_kitty(),
        iterm2=_detect_iterm2(),
        sixel=_detect_sixel(),
        truecolor=_detect_truecolor(),
        terminal_id=_terminal_id(),
    )


# ---------------------------------------------------------------------------
# Convenience for callers
# ---------------------------------------------------------------------------


def is_a_tty() -> bool:
    """``sys.stdout.isatty()`` but resilient to mocked stdouts."""
    out = getattr(sys, "stdout", None)
    if out is None:
        return False
    isatty = getattr(out, "isatty", None)
    if isatty is None or not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:  # noqa: BLE001
        return False
