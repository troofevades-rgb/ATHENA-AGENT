"""Plan-mode listener notification.

The REPL registers a callback at startup so the TUI gets an
immediate StatusUpdateEvent when plan-mode flips — instead of
waiting for the next natural ``_push_status`` (which can be a full
turn away when the model calls EnterPlanMode mid-turn).

These tests pin the contract:
  * enter_plan_mode fires listeners with True
  * exit_plan_mode_silent fires listeners with False
  * Idempotent calls (already in / out of plan mode) do NOT re-fire
  * A listener that raises does not break plan-mode transitions
  * Multiple listeners all fire
"""

from __future__ import annotations

import pytest

from athena.tools import plan as plan_mod


@pytest.fixture(autouse=True)
def _clean_plan_state():
    """Reset module-level state between tests so a listener leaked
    from one test can't break the next."""
    plan_mod._LISTENERS.clear()
    if plan_mod.is_plan_mode():
        plan_mod._PLAN_MODE = False
    yield
    plan_mod._LISTENERS.clear()
    if plan_mod.is_plan_mode():
        plan_mod._PLAN_MODE = False


def test_enter_plan_mode_fires_listener_with_true() -> None:
    seen: list[bool] = []
    plan_mod.register_plan_mode_listener(seen.append)
    plan_mod.enter_plan_mode()
    assert seen == [True]


def test_exit_plan_mode_fires_listener_with_false() -> None:
    seen: list[bool] = []
    plan_mod.enter_plan_mode()  # set state first
    plan_mod.register_plan_mode_listener(seen.append)
    plan_mod.exit_plan_mode_silent()
    assert seen == [False]


def test_enter_twice_only_fires_once() -> None:
    """Idempotent — second enter is a no-op. Without this, a
    status-pushing listener would spam the TUI on every redundant
    EnterPlanMode call."""
    seen: list[bool] = []
    plan_mod.register_plan_mode_listener(seen.append)
    plan_mod.enter_plan_mode()
    plan_mod.enter_plan_mode()
    plan_mod.enter_plan_mode()
    assert seen == [True]


def test_exit_twice_only_fires_once() -> None:
    seen: list[bool] = []
    plan_mod.enter_plan_mode()
    plan_mod.register_plan_mode_listener(seen.append)
    plan_mod.exit_plan_mode_silent()
    plan_mod.exit_plan_mode_silent()
    assert seen == [False]


def test_multiple_listeners_all_fire() -> None:
    seen_a: list[bool] = []
    seen_b: list[bool] = []
    plan_mod.register_plan_mode_listener(seen_a.append)
    plan_mod.register_plan_mode_listener(seen_b.append)
    plan_mod.enter_plan_mode()
    plan_mod.exit_plan_mode_silent()
    assert seen_a == [True, False]
    assert seen_b == [True, False]


def test_listener_exception_does_not_block_transition() -> None:
    """A buggy listener (e.g. TUI gateway temporarily broken) must
    not prevent the plan-mode state change OR prevent other
    listeners from firing."""
    fired: list[bool] = []

    def _bad(_: bool) -> None:
        raise RuntimeError("simulated listener failure")

    plan_mod.register_plan_mode_listener(_bad)
    plan_mod.register_plan_mode_listener(fired.append)
    plan_mod.enter_plan_mode()
    # State changed despite bad listener
    assert plan_mod.is_plan_mode() is True
    # Good listener still fired
    assert fired == [True]


def test_register_is_idempotent_same_function() -> None:
    """Registering the same callable twice shouldn't cause double
    notification — would cause the TUI to receive 2 status pushes
    per transition for no reason."""
    seen: list[bool] = []
    plan_mod.register_plan_mode_listener(seen.append)
    plan_mod.register_plan_mode_listener(seen.append)
    plan_mod.enter_plan_mode()
    assert seen == [True]
