"""Kill-switch tests (T6-04.2).

The switch is module-level state; tests reset between cases via
:func:`athena.computer.killswitch.reset_for_tests`.
"""

from __future__ import annotations

import os
import signal
import threading
import time

import pytest

from athena.computer import killswitch


@pytest.fixture(autouse=True)
def _reset():
    """Clean kill-switch state before AND after every test —
    the module's global state would otherwise leak between
    test cases."""
    killswitch.reset_for_tests()
    yield
    killswitch.reset_for_tests()


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_killswitch_starts_disengaged():
    assert killswitch.is_engaged() is False
    assert killswitch.engaged_reason() is None


def test_poll_for_halt_initial():
    decision = killswitch.poll_for_halt()
    assert decision.halted is False
    assert decision.reason is None


# ---------------------------------------------------------------------------
# Manual engage / disengage
# ---------------------------------------------------------------------------


def test_engage_sets_flag():
    killswitch.engage(reason="test request")
    assert killswitch.is_engaged() is True
    assert killswitch.engaged_reason() == "test request"


def test_engage_idempotent_preserves_first_reason():
    killswitch.engage(reason="first")
    killswitch.engage(reason="second")
    assert killswitch.engaged_reason() == "first"


def test_disengage_clears_flag():
    killswitch.engage(reason="x")
    killswitch.disengage()
    assert killswitch.is_engaged() is False
    assert killswitch.engaged_reason() is None


def test_poll_for_halt_reflects_engagement():
    killswitch.engage(reason="manual")
    decision = killswitch.poll_for_halt()
    assert decision.halted is True
    assert decision.reason == "manual"


# ---------------------------------------------------------------------------
# Loop polling integration
# ---------------------------------------------------------------------------


def test_loop_polls_and_halts():
    """Simulate a tight stub loop polling is_engaged() at the
    top of each iteration. After three iterations engage; the
    loop should exit before the next iteration."""
    iterations = 0

    def _stub_loop() -> str:
        nonlocal iterations
        while iterations < 100:  # safety bound — kill switch
                                 # should halt us before this
            if killswitch.is_engaged():
                return "halted"
            iterations += 1
            if iterations == 3:
                # Mid-loop external engagement (mirrors the
                # SIGINT or hotkey path firing from a different
                # thread / signal handler).
                killswitch.engage(reason="mid-loop")
        return "max-iterations"

    result = _stub_loop()
    assert result == "halted"
    # The check at the TOP of iteration 4 saw the engagement.
    assert iterations == 3


def test_loop_runs_normally_when_disengaged():
    """A loop that never trips the switch runs to completion —
    pinning that polling is_engaged() doesn't have a side
    effect that would falsely halt."""
    iterations = 0
    for _ in range(5):
        if killswitch.is_engaged():
            break
        iterations += 1
    assert iterations == 5


# ---------------------------------------------------------------------------
# Ctrl+C engages (SIGINT path)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(signal, "SIGINT") or os.name == "nt",
    reason="SIGINT semantics differ on Windows; the engage path is verified by direct call",
)
def test_ctrl_c_engages_via_signal():
    """When armed, a real SIGINT engages the switch — and
    KeyboardInterrupt propagates as it always has so the rest
    of the agent's interrupt handling still fires."""
    killswitch.arm(hotkey=None)
    try:
        with pytest.raises(KeyboardInterrupt):
            os.kill(os.getpid(), signal.SIGINT)
            # Give the handler a moment to run on slow CI.
            time.sleep(0.05)
        assert killswitch.is_engaged() is True
        assert killswitch.engaged_reason() == "Ctrl+C"
    finally:
        killswitch.disengage()


def test_ctrl_c_engages_via_handler_call():
    """Cross-platform variant: invoke the SIGINT handler
    directly (what signal.signal would call). Verifies the
    same engagement contract without relying on os.kill(...)
    semantics."""
    killswitch.arm(hotkey=None)
    try:
        with pytest.raises(KeyboardInterrupt):
            killswitch._sigint_handler(signal.SIGINT, None)
        assert killswitch.is_engaged() is True
        assert killswitch.engaged_reason() == "Ctrl+C"
    finally:
        killswitch.disengage()


def test_arm_is_idempotent():
    killswitch.arm(hotkey=None)
    killswitch.arm(hotkey=None)  # second call no-ops
    killswitch.disengage()
    assert killswitch.is_engaged() is False


def test_arm_clears_stale_engagement():
    """If the switch was left engaged from a prior session,
    arm() resets it — otherwise the first action of the next
    session would immediately halt."""
    killswitch.engage(reason="stale")
    killswitch.arm(hotkey=None)
    try:
        assert killswitch.is_engaged() is False
    finally:
        killswitch.disengage()


# ---------------------------------------------------------------------------
# Hotkey parsing (best-effort; pynput optional)
# ---------------------------------------------------------------------------


def test_hotkey_parse_round_trip():
    """Parse the standard "ctrl+alt+k" form into pynput's
    "<ctrl>+<alt>+k". Pure function — no pynput needed."""
    assert killswitch._parse_hotkey("ctrl+alt+k") == "<ctrl>+<alt>+k"
    assert killswitch._parse_hotkey("Cmd+Q") == "<cmd>+q"
    assert killswitch._parse_hotkey("shift+f5") == "<shift>+<f5>"


def test_hotkey_parse_bad_input():
    assert killswitch._parse_hotkey("") is None
    assert killswitch._parse_hotkey("+") is None


def test_hotkey_listener_silent_when_pynput_absent(monkeypatch):
    """When pynput isn't installed, _try_start_hotkey_listener
    returns None and Ctrl+C remains the active path."""
    # Force the ImportError branch by replacing the (possibly
    # already-imported) pynput module.
    import sys as _sys

    monkeypatch.setitem(
        _sys.modules,
        "pynput",
        None,  # any import from `pynput` raises
    )
    listener = killswitch._try_start_hotkey_listener("ctrl+alt+k")
    assert listener is None
