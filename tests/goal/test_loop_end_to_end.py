"""End-to-end tests for the goal continuation loop.

The existing tests/goal/ suite covers sentinel detection, prompt
building, state persistence, and the decision matrix individually.
What's missing — and what these tests add — is the FULL DRIVER
behavior: a goal is set, ``maybe_continue_goal_after_turn`` fires
between turns, state mutates correctly across many iterations,
and the loop terminates on the right signals (achieved, blocked,
exhausted, verifier rejection).

No real LLM here. We simulate model output by directly invoking
``maybe_continue_goal_after_turn`` with chosen assistant text,
verifying the state machine transitions and the synthetic-prompt
content correctly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.goal.loop import (
    ContinuationDecision,
    maybe_continue_goal_after_turn,
)
from athena.goal.state import GoalState


def _state(**overrides) -> GoalState:
    """Build a GoalState with sensible test defaults."""
    base = {
        "goal_id": "g-test",
        "text": "make the test pass",
        "status": "active",
        "turns_taken": 0,
        "max_turns": 5,
        "subgoals": [],
    }
    base.update(overrides)
    return GoalState(**base)


def _cfg(**overrides) -> SimpleNamespace:
    """Minimal cfg with the fields the loop reads."""
    base = {
        "goal_loop_enabled": True,
        "goal_verifier_command": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Multi-turn driver simulation
# ---------------------------------------------------------------------------


def test_loop_drives_multiple_turns_then_terminates_on_achieved(
    tmp_path: Path,
) -> None:
    """Simulate a 4-turn goal run: 3 turns of working, then GOAL
    ACHIEVED. Verify state.turns_taken increments correctly and
    the loop terminates on the right turn."""
    state = _state(max_turns=10)
    cfg = _cfg()

    # Turn 1: model is working
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Started analyzing the test.",
        cfg=cfg,
    )
    assert d.should_continue is True
    assert state.turns_taken == 1
    assert state.status == "active"

    # Turn 2: still working
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Fixed one assertion.",
        cfg=cfg,
    )
    assert d.should_continue is True
    assert state.turns_taken == 2

    # Turn 3: still working
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Refactored the helper.",
        cfg=cfg,
    )
    assert d.should_continue is True
    assert state.turns_taken == 3

    # Turn 4: GOAL ACHIEVED — loop must terminate
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="All tests pass.\nGOAL ACHIEVED",
        cfg=cfg,
    )
    assert d.should_continue is False
    assert d.stop_reason == "achieved"
    assert state.status == "achieved"


def test_loop_terminates_on_goal_blocked_sentinel(tmp_path: Path) -> None:
    """The model can signal it's stuck and needs the user. The loop
    must stop and surface the reason."""
    state = _state()

    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text=(
            "I need the API token to continue.\n"
            "GOAL BLOCKED: missing ATHENA_X_BEARER_TOKEN"
        ),
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "blocked"
    assert "ATHENA_X_BEARER_TOKEN" in (d.blocked_reason or "")
    assert state.status == "paused"


def test_loop_terminates_on_max_turns_reached(tmp_path: Path) -> None:
    """When turns_taken hits max_turns, the loop must mark
    ``exhausted`` and not inject another continuation. Without
    this cap, a model that never emits a sentinel would run
    forever."""
    state = _state(max_turns=3)
    cfg = _cfg()

    # Walk to the cap
    for i in range(3):
        d = maybe_continue_goal_after_turn(
            profile_dir=tmp_path, state=state,
            last_assistant_text=f"Working step {i+1}.",
            cfg=cfg,
        )
        # Each turn before the cap should continue
        if i < 2:
            assert d.should_continue is True, f"turn {i} stopped early"

    # state.turns_taken should now be at cap (3), status should be
    # 'exhausted' OR the next call returns exhausted.
    if state.status != "exhausted":
        d = maybe_continue_goal_after_turn(
            profile_dir=tmp_path, state=state,
            last_assistant_text="Still working.",
            cfg=cfg,
        )
        assert d.should_continue is False
        assert d.stop_reason == "exhausted"


def test_loop_returns_disabled_when_cfg_says_so(tmp_path: Path) -> None:
    """An operator override (cfg.goal_loop_enabled=False) must short-
    circuit the entire driver regardless of state."""
    state = _state()
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Working on it.",
        cfg=_cfg(goal_loop_enabled=False),
    )
    assert d.should_continue is False
    assert d.stop_reason == "disabled"
    # State unchanged
    assert state.turns_taken == 0
    assert state.status == "active"


def test_no_state_means_no_continuation(tmp_path: Path) -> None:
    """When no goal is set, the driver must be a strict no-op."""
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=None,
        last_assistant_text="Anything goes here.",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "no_state"


# ---------------------------------------------------------------------------
# State persistence across decisions
# ---------------------------------------------------------------------------


def test_state_persists_between_turns(tmp_path: Path) -> None:
    """maybe_continue must write the bumped state to disk so a
    restart picks up the right turn counter."""
    state = _state(max_turns=5)
    cfg = _cfg()

    for i in range(3):
        maybe_continue_goal_after_turn(
            profile_dir=tmp_path, state=state,
            last_assistant_text=f"Step {i}",
            cfg=cfg,
        )

    # Reload from disk and verify
    from athena.goal.state import load_state
    loaded = load_state(tmp_path)
    assert loaded is not None
    assert loaded.turns_taken == 3
    assert loaded.status == "active"


def test_paused_state_returns_paused_without_advancing(tmp_path: Path) -> None:
    """Once a goal is paused (via /goal pause), the driver must
    NOT keep firing continuations even if the model output looks
    fine. The user has to /goal resume first."""
    state = _state(status="paused", turns_taken=2)

    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Working away.",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "paused"
    # Turn counter unchanged — paused doesn't bump
    assert state.turns_taken == 2


# ---------------------------------------------------------------------------
# Verifier integration
# ---------------------------------------------------------------------------


def test_verifier_rejection_keeps_loop_alive_and_bumps_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the model emits GOAL ACHIEVED but the verifier command
    exits non-zero, the loop must:
      - NOT mark achieved
      - bump turns_taken (failed-claim attempts count toward cap)
      - inject the verifier output as the next synthetic prompt
    """
    from athena.goal import loop as loop_mod

    # Stub run_goal_verifier to simulate a failing test run
    from athena.goal.loop import VerifierResult
    monkeypatch.setattr(
        loop_mod, "run_goal_verifier",
        lambda cfg: VerifierResult(
            passed=False,
            output="FAIL: tests/test_widget.py::test_color  expected red got green",
        ),
    )

    state = _state(max_turns=10, turns_taken=2)
    cfg = _cfg(goal_verifier_command="pytest tests/test_widget.py")

    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Done.\nGOAL ACHIEVED",
        cfg=cfg,
    )
    # Rejected — must continue with feedback
    assert d.should_continue is True
    assert state.status == "active"  # NOT achieved
    assert state.turns_taken == 3    # bumped (failed claim costs a turn)
    # Synthetic prompt must surface the rejection + verifier output
    assert d.synthetic_prompt is not None
    assert "rejected" in d.synthetic_prompt.lower()
    assert "expected red got green" in d.synthetic_prompt


def test_verifier_rejection_at_max_turns_marks_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the verifier rejects on the LAST allowed turn, the loop
    must mark ``exhausted`` rather than letting the model loop
    forever claiming done."""
    from athena.goal import loop as loop_mod
    from athena.goal.loop import VerifierResult

    monkeypatch.setattr(
        loop_mod, "run_goal_verifier",
        lambda cfg: VerifierResult(passed=False, output="STILL FAILING"),
    )

    # turns_taken = max_turns - 1 → after the failed-claim bump it equals max
    state = _state(max_turns=3, turns_taken=2)
    cfg = _cfg(goal_verifier_command="false")

    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Tried.\nGOAL ACHIEVED",
        cfg=cfg,
    )
    assert d.should_continue is False
    assert d.stop_reason == "exhausted"
    assert state.status == "exhausted"


def test_verifier_pass_accepts_achievement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the verifier passes, achievement stands."""
    from athena.goal import loop as loop_mod
    from athena.goal.loop import VerifierResult

    monkeypatch.setattr(
        loop_mod, "run_goal_verifier",
        lambda cfg: VerifierResult(passed=True, output="ok"),
    )

    state = _state(max_turns=10, turns_taken=2)
    cfg = _cfg(goal_verifier_command="true")

    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=state,
        last_assistant_text="Done.\nGOAL ACHIEVED",
        cfg=cfg,
    )
    assert d.should_continue is False
    assert d.stop_reason == "achieved"
    assert state.status == "achieved"
