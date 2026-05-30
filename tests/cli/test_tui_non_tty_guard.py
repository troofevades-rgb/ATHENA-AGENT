"""``_run_interactive_repl`` refuses to launch the Ink TUI when
stdin or stdout isn't a TTY.

The Ink subprocess needs raw-mode stdin (single-keypress capture)
and a real terminal for its render. Inheriting a piped/redirected
stdio crashes Ink deep inside ``setRawMode`` with
``Error: Raw mode is not supported on the current process.stdin``
-- a stacktrace from JS code the user can't act on. The parent
then waits at "connecting to gateway..." until the accept-timeout
fires and surfaces "TUI did not start -- bundle probably failed
to start", which is wrong: the bundle launched fine; its stdio
was broken.

The guard turns that misleading sequence into a single clear
message with concrete next steps before any subprocess is spawned.
"""

from __future__ import annotations

import sys

import pytest

from athena import __main__ as athena_main


class _FakeStdio:
    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_non_tty_stdin_aborts_before_spawning_ink(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Piped stdin (``echo hi | athena``) -> the guard fires before
    TuiGateway() is constructed, so the Ink subprocess never runs and
    the user sees the clear-error path."""
    monkeypatch.setenv("ATHENA_TUI_NONINTERACTIVE", "")
    monkeypatch.setattr(sys, "stdin", _FakeStdio(False))
    monkeypatch.setattr(sys, "stdout", _FakeStdio(True))

    # If the guard misses, _run_interactive_repl would reach the
    # TuiGateway() construction below and fail differently. Patch it
    # to a sentinel that detects the miss.
    constructed = []

    class _Sentinel:
        def __init__(self, *a, **kw) -> None:
            constructed.append((a, kw))

        def start(self) -> None:
            raise AssertionError("guard missed -- TuiGateway.start() reached")

    monkeypatch.setattr(
        "athena.tui_gateway.TuiGateway",
        _Sentinel,
    )

    code = athena_main._run_interactive_repl(agent=None, cfg=None, workspace=None)

    assert code == 2
    assert constructed == []
    captured = capsys.readouterr()
    # Single line "cannot start the interactive TUI" header + at
    # least one concrete-next-step bullet.
    assert "cannot start the interactive TUI" in captured.err
    assert "winpty" in captured.err  # workaround surfaced
    assert "-p" in captured.err  # headless escape hatch surfaced


def test_non_tty_stdout_also_aborts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``athena | tee log.txt`` -> stdout isn't a TTY -> same guard."""
    monkeypatch.setenv("ATHENA_TUI_NONINTERACTIVE", "")
    monkeypatch.setattr(sys, "stdin", _FakeStdio(True))
    monkeypatch.setattr(sys, "stdout", _FakeStdio(False))

    monkeypatch.setattr(
        "athena.tui_gateway.TuiGateway",
        lambda *a, **kw: pytest.fail("guard missed"),
    )

    code = athena_main._run_interactive_repl(agent=None, cfg=None, workspace=None)
    assert code == 2
    assert "not a terminal" in capsys.readouterr().err


def test_athena_tui_noninteractive_env_var_bypasses_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ATHENA_TUI_NONINTERACTIVE=1`` lets the guard skip its
    isatty check -- reserved for tests that exercise the
    post-guard branches without needing a real PTY. Verify the
    guard returns control to the TuiGateway() construction below."""
    monkeypatch.setenv("ATHENA_TUI_NONINTERACTIVE", "1")
    monkeypatch.setattr(sys, "stdin", _FakeStdio(False))
    monkeypatch.setattr(sys, "stdout", _FakeStdio(False))

    constructed = []

    class _MarkerGateway:
        def __init__(self, *a, **kw) -> None:
            constructed.append((a, kw))

        def start(self) -> None:
            # Once constructed, we've proven the guard let us through.
            # Raise so _run_interactive_repl returns 2 via its RuntimeError
            # path and the test exits cleanly without spinning up
            # actual node + Ink.
            raise RuntimeError("intentionally aborting after guard pass")

    monkeypatch.setattr(
        "athena.tui_gateway.TuiGateway",
        _MarkerGateway,
    )
    monkeypatch.setattr(
        "athena.tui_gateway.banner_data.build_banner",
        lambda *a, **kw: "fake banner",
    )

    code = athena_main._run_interactive_repl(agent=None, cfg=None, workspace=None)
    assert code == 2  # via the RuntimeError handler below
    assert len(constructed) == 1, (
        "guard should have let TuiGateway() construct when "
        "ATHENA_TUI_NONINTERACTIVE=1"
    )
