"""Tests for the continuation-decision driver (T5-07.3).

Each call to :func:`maybe_continue_goal_after_turn` is one
turn-end. The tests pin the state-transition table — every branch
of the decision tree — and verify that state changes are
persisted to disk so a restart mid-loop picks up correctly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.goal.loop import (
    ContinuationDecision,
    maybe_continue_goal_after_turn,
)
from athena.goal.state import GoalState, load_state, save_state


def _cfg(**overrides) -> SimpleNamespace:
    base = {
        "goal_loop_enabled": True,
        "goal_max_turns": 25,
        "goal_max_tokens": 200_000,
        "goal_continuation_prompt": None,
        "goal_achieved_sentinel": "GOAL ACHIEVED",
        "goal_blocked_sentinel": "GOAL BLOCKED",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Achievement / blocked
# ---------------------------------------------------------------------------


def test_loop_stops_on_achieved(tmp_path: Path):
    """Sentinel fires → status flipped to achieved, persisted,
    decision stops."""
    st = GoalState(text="finish it")
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="all done.\nGOAL ACHIEVED",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "achieved"
    assert st.status == "achieved"
    # Persisted
    back = load_state(tmp_path)
    assert back is not None
    assert back.status == "achieved"


def test_loop_stops_on_blocked_with_reason(tmp_path: Path):
    st = GoalState(text="finish it")
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="need help.\nGOAL BLOCKED: missing credentials",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "blocked"
    assert d.blocked_reason == "missing credentials"
    assert st.status == "paused"
    back = load_state(tmp_path)
    assert back is not None
    assert back.status == "paused"


# ---------------------------------------------------------------------------
# Active path
# ---------------------------------------------------------------------------


def test_loop_continues_when_active(tmp_path: Path):
    st = GoalState(text="x", max_turns=5)
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="still working...",
        cfg=_cfg(),
    )
    assert d.should_continue is True
    assert d.synthetic_prompt is not None
    assert "GOAL ACHIEVED" in d.synthetic_prompt
    assert "GOAL BLOCKED" in d.synthetic_prompt
    assert st.turns_taken == 1


def test_loop_uses_cfg_override_prompt(tmp_path: Path):
    st = GoalState(text="x", max_turns=5)
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="continuing",
        cfg=_cfg(goal_continuation_prompt="keep at it, fam"),
    )
    assert d.should_continue is True
    assert d.synthetic_prompt == "keep at it, fam"


# ---------------------------------------------------------------------------
# Exhaustion cap
# ---------------------------------------------------------------------------


def test_loop_exhausts_at_cap(tmp_path: Path):
    """max_turns=1 → the very first call bumps to 1 and exhausts.
    The whole point of the cap is preventing runaway."""
    st = GoalState(text="x", max_turns=1)
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="working...",
        cfg=_cfg(),
    )
    assert d.stop_reason == "exhausted"
    assert st.status == "exhausted"
    assert st.turns_taken == 1


def test_loop_at_cap_does_not_bump_further(tmp_path: Path):
    """A state already at cap → caller calls hook again → still
    exhausted, turns_taken doesn't grow further."""
    st = GoalState(text="x", status="exhausted", turns_taken=25, max_turns=25)
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="...",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "exhausted"
    assert st.turns_taken == 25  # no further bump


# ---------------------------------------------------------------------------
# Status guard
# ---------------------------------------------------------------------------


def test_paused_goal_does_not_continue(tmp_path: Path):
    st = GoalState(text="x", status="paused")
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="still working",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "paused"
    assert st.turns_taken == 0  # no bump


def test_achieved_state_returns_achieved_stop_reason(tmp_path: Path):
    st = GoalState(text="x", status="achieved")
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="oh look more work",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "achieved"


# ---------------------------------------------------------------------------
# Disabled / no-state
# ---------------------------------------------------------------------------


def test_disabled_does_not_continue(tmp_path: Path):
    st = GoalState(text="x")
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="working",
        cfg=_cfg(goal_loop_enabled=False),
    )
    assert d.should_continue is False
    assert d.stop_reason == "disabled"
    # Disabled is a hard short-circuit — no turn bump, no
    # persistence.
    assert st.turns_taken == 0


def test_no_state_returns_no_state(tmp_path: Path):
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=None,
        last_assistant_text="ok",
        cfg=_cfg(),
    )
    assert d.should_continue is False
    assert d.stop_reason == "no_state"


# ---------------------------------------------------------------------------
# Persistence behaviour
# ---------------------------------------------------------------------------


def test_active_continuation_persists_turn_counter(tmp_path: Path):
    """Each active continuation persists turns_taken so a restart
    in the middle of a loop reads the right turn number."""
    st = GoalState(text="x", max_turns=5)
    maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=st, last_assistant_text="a", cfg=_cfg()
    )
    maybe_continue_goal_after_turn(
        profile_dir=tmp_path, state=st, last_assistant_text="b", cfg=_cfg()
    )
    back = load_state(tmp_path)
    assert back is not None
    assert back.turns_taken == 2


def test_persistence_failure_does_not_block_decision(tmp_path: Path, monkeypatch):
    """A disk error during save_state doesn't change the
    in-memory decision — the loop still tells the caller to
    continue (or stop), the persistence is best-effort."""
    def _boom(*a, **kw):
        raise OSError("disk full (synthetic)")

    monkeypatch.setattr("athena.goal.loop.save_state", _boom)
    st = GoalState(text="x", max_turns=5)
    d = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=st,
        last_assistant_text="working",
        cfg=_cfg(),
    )
    assert d.should_continue is True
    assert st.turns_taken == 1  # mutated in-memory regardless
