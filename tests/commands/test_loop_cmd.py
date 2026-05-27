"""Tests for ``/loop INTERVAL CMD`` and ``/loop-stop``.

The loop module holds a thread + module-level ``_LOOP`` state.
We patch ``threading.Thread`` so we never actually spawn a daemon
thread during tests (would leave runaway threads on failure), and
exercise the parser + state-replacement logic directly.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from athena.commands import loop as loop_mod
from athena.commands.loop import _parse, cmd_loop, cmd_loop_stop


@pytest.fixture(autouse=True)
def _reset_loop_state():
    """Clear ``_LOOP`` before AND after each test. Stops any thread
    a test left behind by setting its stop event."""
    if loop_mod._LOOP is not None:
        loop_mod._LOOP["stop"].set()
        loop_mod._LOOP = None
    yield
    if loop_mod._LOOP is not None:
        loop_mod._LOOP["stop"].set()
        loop_mod._LOOP = None


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.loop.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    return lines, patches


def _run(cmd_fn, arg: str) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        cmd_fn(SimpleNamespace(), arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


# ---- _parse ---------------------------------------------------------


def test_parse_with_seconds_unit() -> None:
    result = _parse("30s do something")
    assert result == (30.0, "do something")


def test_parse_with_minutes_unit() -> None:
    result = _parse("5m check the build")
    assert result == (300.0, "check the build")


def test_parse_with_hours_unit() -> None:
    result = _parse("2h /review")
    assert result == (7200.0, "/review")


def test_parse_defaults_to_minutes_when_unit_missing() -> None:
    """Per the regex: `\\d+` followed by optional `[smh]`. When the
    unit is missing, the multiplier should be minutes (per the
    dict lookup with default 'm')."""
    result = _parse("10 just a number")
    assert result == (600.0, "just a number")  # 10 * 60s


def test_parse_strips_whitespace_around_interval() -> None:
    result = _parse("  5s  hello world  ")
    assert result == (5.0, "hello world")


def test_parse_returns_none_on_empty_body() -> None:
    assert _parse("5m") is None
    assert _parse("5m   ") is None


def test_parse_returns_none_on_malformed_input() -> None:
    assert _parse("xyz nonsense") is None
    assert _parse("") is None


def test_parse_handles_slash_body() -> None:
    """The body can start with `/` (slash command) — must be passed
    through verbatim, not eaten by the regex."""
    assert _parse("1m /review") == (60.0, "/review")
    assert _parse("30s /board clear") == (30.0, "/board clear")


# ---- /loop ----------------------------------------------------------


def test_loop_with_invalid_arg_errors_and_does_not_start() -> None:
    out = _run(cmd_loop, "garbage")
    assert "usage" in out.lower()
    assert loop_mod._LOOP is None


def test_loop_starts_thread_and_records_state() -> None:
    """Successful /loop must populate _LOOP and start a daemon
    thread. We patch threading.Thread so no real thread fires."""
    fake_thread = MagicMock()
    with patch("athena.commands.loop.threading.Thread", return_value=fake_thread):
        out = _run(cmd_loop, "5m /review")
    assert loop_mod._LOOP is not None
    assert loop_mod._LOOP["body"] == "/review"
    assert loop_mod._LOOP["interval"] == 300.0
    fake_thread.start.assert_called_once()
    # User-facing confirmation
    assert "loop scheduled" in out.lower()
    assert "300s" in out
    assert "/review" in out
    assert "/loop-stop" in out  # tells user how to cancel


def test_loop_replaces_existing_loop() -> None:
    """Starting a /loop while one is running stops the old one
    and replaces _LOOP, with a 'replacing' warning."""
    fake_thread = MagicMock()
    with patch("athena.commands.loop.threading.Thread", return_value=fake_thread):
        _run(cmd_loop, "5m first")
    first_stop = loop_mod._LOOP["stop"]

    with patch("athena.commands.loop.threading.Thread", return_value=fake_thread):
        out = _run(cmd_loop, "1m second")
    # Old stop event was signalled
    assert first_stop.is_set()
    # New loop in place
    assert loop_mod._LOOP["body"] == "second"
    assert loop_mod._LOOP["interval"] == 60.0
    assert "replacing" in out.lower()


# ---- /loop-stop -----------------------------------------------------


def test_loop_stop_with_no_loop_running_is_a_noop() -> None:
    out = _run(cmd_loop_stop, "")
    assert "no loop running" in out.lower()
    assert loop_mod._LOOP is None


def test_loop_stop_clears_state_and_signals_stop() -> None:
    fake_thread = MagicMock()
    with patch("athena.commands.loop.threading.Thread", return_value=fake_thread):
        _run(cmd_loop, "5m /review")
    stop_event = loop_mod._LOOP["stop"]
    out = _run(cmd_loop_stop, "")
    assert stop_event.is_set()
    assert loop_mod._LOOP is None
    assert "loop stopped" in out.lower()
