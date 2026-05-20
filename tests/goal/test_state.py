"""Tests for the goal-state persistence model (T5-07.2).

State is a JSON file alongside the human-editable goal.txt;
load/save are defensive (corrupt → None) and the
:meth:`can_continue` predicate is the loop's stop signal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.goal.state import (
    GoalState,
    Subgoal,
    clear_state,
    load_state,
    save_state,
    state_path,
)


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------


def test_state_roundtrip(tmp_path: Path):
    """save → load reproduces every field."""
    st = GoalState(text="migrate utils.py", max_turns=12)
    save_state(tmp_path, st)
    back = load_state(tmp_path)
    assert back is not None
    assert back.text == "migrate utils.py"
    assert back.max_turns == 12
    assert back.status == "active"
    assert back.turns_taken == 0


def test_state_roundtrip_with_subgoals(tmp_path: Path):
    """Subgoals + done flags survive the roundtrip in order."""
    st = GoalState(
        text="ship feature X",
        subgoals=[
            Subgoal("write tests", done=True),
            Subgoal("update docs"),
            Subgoal("changelog entry"),
        ],
    )
    save_state(tmp_path, st)
    back = load_state(tmp_path)
    assert back is not None
    assert [sg.text for sg in back.subgoals] == [
        "write tests",
        "update docs",
        "changelog entry",
    ]
    assert back.subgoals[0].done is True
    assert back.subgoals[1].done is False
    assert back.subgoals[2].done is False


# ---------------------------------------------------------------------------
# can_continue contract
# ---------------------------------------------------------------------------


def test_can_continue_active_under_cap():
    st = GoalState(text="x", status="active", turns_taken=5, max_turns=25)
    assert st.can_continue() is True


def test_can_continue_false_when_paused():
    st = GoalState(text="x", status="paused", turns_taken=0, max_turns=25)
    assert st.can_continue() is False


def test_can_continue_false_at_cap():
    """turns_taken == max_turns is the boundary — already exhausted."""
    st = GoalState(text="x", status="active", turns_taken=25, max_turns=25)
    assert st.can_continue() is False


def test_can_continue_false_when_achieved():
    st = GoalState(text="x", status="achieved")
    assert st.can_continue() is False


def test_can_continue_false_when_exhausted():
    st = GoalState(text="x", status="exhausted", turns_taken=25, max_turns=25)
    assert st.can_continue() is False


# ---------------------------------------------------------------------------
# load_state defensive behaviour
# ---------------------------------------------------------------------------


def test_load_missing_returns_none(tmp_path: Path):
    assert load_state(tmp_path) is None


def test_load_corrupt_returns_none(tmp_path: Path):
    """A malformed state file → None, not an exception. The
    session must keep starting even when the state JSON is
    broken — the user can just /goal clear + re-set."""
    state_path(tmp_path).write_text("not json {{{", encoding="utf-8")
    assert load_state(tmp_path) is None


def test_load_unknown_status_normalises_to_active(tmp_path: Path):
    """Forward-compat: a status we don't recognise (older / newer
    version) doesn't crash — falls through to active so the user
    keeps their goal."""
    state_path(tmp_path).write_text(
        json.dumps({"text": "x", "status": "weirdo"}), encoding="utf-8"
    )
    st = load_state(tmp_path)
    assert st is not None
    assert st.status == "active"


# ---------------------------------------------------------------------------
# save_state behaviour
# ---------------------------------------------------------------------------


def test_save_creates_parent_dir(tmp_path: Path):
    """A fresh profile dir might not exist yet. save_state must
    not require the caller to have made it first."""
    fresh = tmp_path / "newly_minted_profile"
    st = GoalState(text="x")
    p = save_state(fresh, st)
    assert p.exists()
    assert p.parent == fresh


def test_save_bumps_updated_at(tmp_path: Path):
    """Each save touches updated_at — operational tooling can
    watch that timestamp to see when the loop last advanced."""
    st = GoalState(text="x")
    old = st.updated_at
    # Force a different timestamp.
    import time as _t

    _t.sleep(0.01)
    save_state(tmp_path, st)
    assert st.updated_at > old


# ---------------------------------------------------------------------------
# first_pending_subgoal + clear
# ---------------------------------------------------------------------------


def test_first_pending_subgoal():
    st = GoalState(
        text="x",
        subgoals=[
            Subgoal("a", done=True),
            Subgoal("b", done=False),
            Subgoal("c", done=False),
        ],
    )
    pending = st.first_pending_subgoal()
    assert pending is not None
    assert pending.text == "b"


def test_first_pending_subgoal_none_when_all_done():
    st = GoalState(
        text="x",
        subgoals=[Subgoal("a", done=True), Subgoal("b", done=True)],
    )
    assert st.first_pending_subgoal() is None


def test_clear_state_when_present(tmp_path: Path):
    save_state(tmp_path, GoalState(text="x"))
    assert clear_state(tmp_path) is True
    assert load_state(tmp_path) is None


def test_clear_state_when_absent(tmp_path: Path):
    assert clear_state(tmp_path) is False
