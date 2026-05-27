"""Detection tests for ``athena.tui_gateway.terminal_caps``.

Zero coverage today. This module decides which image-protocol the
gateway uses to render the banner / wordmark — a wrong detection
means either (a) garbage characters dumped into the user's terminal,
or (b) silently falling back to ASCII art for a terminal that COULD
do graphics.

The detection logic is pure env-var sniff, so the tests can run on
any platform by monkeypatching ``os.environ``.
"""

from __future__ import annotations

import pytest

from athena.tui_gateway.terminal_caps import (
    TerminalCaps,
    detect_caps,
    is_a_tty,
)


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clean slate: drop every env var that detect_caps looks at so
    one test's setup doesn't leak into another via the real shell
    env (CI variability)."""
    for name in (
        "KITTY_WINDOW_ID", "TERM_PROGRAM", "GHOSTTY_RESOURCES_DIR",
        "LC_TERMINAL", "ATHENA_FORCE_SIXEL", "WT_SESSION",
        "COLORTERM", "TERM",
    ):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# best_image_protocol() priority order
# ---------------------------------------------------------------------------


def test_priority_kitty_over_iterm2_over_sixel() -> None:
    """When multiple protocols are supported, pick Kitty > iterm2 > sixel."""
    caps = TerminalCaps(
        kitty=True, iterm2=True, sixel=True, truecolor=True,
        terminal_id="multi",
    )
    assert caps.best_image_protocol() == "kitty"

    caps = TerminalCaps(
        kitty=False, iterm2=True, sixel=True, truecolor=True,
        terminal_id="multi-no-kitty",
    )
    assert caps.best_image_protocol() == "iterm2"

    caps = TerminalCaps(
        kitty=False, iterm2=False, sixel=True, truecolor=True,
        terminal_id="sixel-only",
    )
    assert caps.best_image_protocol() == "sixel"


def test_no_protocols_returns_none_string() -> None:
    """All-false → return the literal string 'none', not None.
    Caller code may concatenate it into a log message and a None
    would raise TypeError."""
    caps = TerminalCaps(
        kitty=False, iterm2=False, sixel=False, truecolor=False,
        terminal_id="plain",
    )
    assert caps.best_image_protocol() == "none"


# ---------------------------------------------------------------------------
# Kitty detection
# ---------------------------------------------------------------------------


def test_detects_kitty_via_kitty_window_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KITTY_WINDOW_ID", "42")
    caps = detect_caps()
    assert caps.kitty is True


def test_detects_kitty_via_wezterm_term_program(monkeypatch: pytest.MonkeyPatch) -> None:
    """WezTerm implements the Kitty protocol but advertises itself
    via TERM_PROGRAM=WezTerm."""
    monkeypatch.setenv("TERM_PROGRAM", "WezTerm")
    caps = detect_caps()
    assert caps.kitty is True


def test_detects_kitty_via_ghostty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHOSTTY_RESOURCES_DIR", "/opt/ghostty")
    caps = detect_caps()
    assert caps.kitty is True


# ---------------------------------------------------------------------------
# iTerm2 detection
# ---------------------------------------------------------------------------


def test_detects_iterm2_via_term_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    caps = detect_caps()
    assert caps.iterm2 is True


def test_detects_iterm2_via_lc_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """LC_TERMINAL=iTerm2 is propagated to tmux/ssh sessions even when
    TERM_PROGRAM gets clobbered."""
    monkeypatch.setenv("LC_TERMINAL", "iTerm2")
    caps = detect_caps()
    assert caps.iterm2 is True


# ---------------------------------------------------------------------------
# Sixel detection — broadest, includes the WT_SESSION heuristic
# ---------------------------------------------------------------------------


def test_force_sixel_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Power-user escape hatch — ATHENA_FORCE_SIXEL=1 must force
    sixel on regardless of terminal detection."""
    monkeypatch.setenv("ATHENA_FORCE_SIXEL", "1")
    caps = detect_caps()
    assert caps.sixel is True


def test_force_sixel_off_disables_wt_session_heuristic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old Windows Terminals (pre 1.22) don't support Sixel. Setting
    ATHENA_FORCE_SIXEL=0 must opt out of the WT_SESSION heuristic
    that otherwise assumes-on."""
    monkeypatch.setenv("WT_SESSION", "abcd")
    monkeypatch.setenv("ATHENA_FORCE_SIXEL", "0")
    caps = detect_caps()
    assert caps.sixel is False, (
        "ATHENA_FORCE_SIXEL=0 must override the WT_SESSION assume-on heuristic"
    )


def test_detects_sixel_in_known_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for tp in ("WezTerm", "mintty", "ghostty", "foot", "contour"):
        monkeypatch.setenv("TERM_PROGRAM", tp)
        caps = detect_caps()
        assert caps.sixel is True, f"failed to detect sixel for {tp}"


def test_detects_sixel_via_term_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "mlterm-256color")
    assert detect_caps().sixel is True
    monkeypatch.setenv("TERM", "xterm-sixel")
    assert detect_caps().sixel is True


def test_plain_xterm_does_not_auto_assume_sixel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """xterm-256color is the most common TERM value but xterm-only-
    binaries don't compile with sixel by default. Must NOT assume yes."""
    monkeypatch.setenv("TERM", "xterm-256color")
    assert detect_caps().sixel is False


# ---------------------------------------------------------------------------
# Truecolor — the most-used capability
# ---------------------------------------------------------------------------


def test_detects_truecolor_via_colorterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for v in ("truecolor", "24bit"):
        monkeypatch.setenv("COLORTERM", v)
        assert detect_caps().truecolor is True, f"failed for COLORTERM={v}"


def test_truecolor_inferred_from_modern_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Major modern terminals support truecolor — caps should reflect
    that even if COLORTERM isn't set."""
    monkeypatch.setenv("KITTY_WINDOW_ID", "9")
    assert detect_caps().truecolor is True

    monkeypatch.delenv("KITTY_WINDOW_ID")
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert detect_caps().truecolor is True


def test_plain_term_without_modern_signals_no_truecolor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No modern signals → don't claim truecolor. Better to use
    256-color and have it look right than 24-bit and get color
    quantization noise."""
    monkeypatch.setenv("TERM", "xterm")
    assert detect_caps().truecolor is False


# ---------------------------------------------------------------------------
# Empty / hostile env — must not crash
# ---------------------------------------------------------------------------


def test_completely_empty_env_returns_all_false() -> None:
    """No env vars → detection returns all-false, no exception. This
    is the "running inside a CI step's bare subprocess" case."""
    caps = detect_caps()
    assert caps.kitty is False
    assert caps.iterm2 is False
    assert caps.sixel is False
    assert caps.truecolor is False
    assert caps.best_image_protocol() == "none"
    assert "TERM=" in caps.terminal_id  # something useful for logs


def test_terminal_id_includes_term_program_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setenv("TERM", "xterm-256color")
    caps = detect_caps()
    assert "iTerm.app" in caps.terminal_id
    assert "xterm-256color" in caps.terminal_id


# ---------------------------------------------------------------------------
# is_a_tty resilience — used by callers gating output on TTY-ness
# ---------------------------------------------------------------------------


def test_is_a_tty_handles_mocked_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some test harnesses replace sys.stdout with an object that
    lacks .isatty(). is_a_tty must not crash — must return False."""
    import sys

    class _NoIsAtty:
        def write(self, s): pass
        def flush(self): pass

    monkeypatch.setattr(sys, "stdout", _NoIsAtty())
    assert is_a_tty() is False


def test_is_a_tty_handles_isatty_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An isatty() implementation that throws (some Jupyter contexts)
    must be caught and treated as 'not a tty'."""
    import sys

    class _ThrowsOnIsAtty:
        def isatty(self): raise OSError("not allowed")
        def write(self, s): pass
        def flush(self): pass

    monkeypatch.setattr(sys, "stdout", _ThrowsOnIsAtty())
    assert is_a_tty() is False


def test_is_a_tty_handles_none_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sys.stdout=None happens in some daemonization contexts."""
    import sys
    monkeypatch.setattr(sys, "stdout", None)
    assert is_a_tty() is False
