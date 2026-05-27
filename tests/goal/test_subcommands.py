"""Tests for /goal subcommands + /subgoal + invariant block rendering (T5-07.4)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.commands.goal import cmd_goal, cmd_subgoal
from athena.goal.invariant import format_for_system_prompt, get_goal
from athena.goal.state import GoalState, Subgoal, load_state, save_state


class _StubAgent:
    """Bare-minimum agent surface the goal commands touch."""

    def __init__(self, profile_dir: Path, max_turns: int = 25):
        self._pdir = profile_dir
        self.cfg = SimpleNamespace(goal_max_turns=max_turns)
        self.reload_called = 0

    def _profile_dir(self):
        return self._pdir

    def reload_goal(self):
        self.reload_called += 1


# ---------------------------------------------------------------------------
# /goal <text>
# ---------------------------------------------------------------------------


def test_goal_set_creates_text_and_state(tmp_path: Path):
    a = _StubAgent(tmp_path, max_turns=10)
    cmd_goal(a, "ship the migration verify command")
    assert get_goal(tmp_path) == "ship the migration verify command"
    st = load_state(tmp_path)
    assert st is not None
    assert st.text == "ship the migration verify command"
    assert st.status == "active"
    assert st.turns_taken == 0
    assert st.max_turns == 10
    assert a.reload_called == 1


def test_goal_replace_resets_state(tmp_path: Path):
    """Setting a new goal text resets turns_taken + status."""
    save_state(
        tmp_path,
        GoalState(text="old", status="exhausted", turns_taken=99, max_turns=25),
    )
    a = _StubAgent(tmp_path, max_turns=15)
    cmd_goal(a, "brand new concrete objective text")
    st = load_state(tmp_path)
    assert st is not None
    assert st.text == "brand new concrete objective text"
    assert st.status == "active"
    assert st.turns_taken == 0
    assert st.max_turns == 15


# ---------------------------------------------------------------------------
# /goal pause / resume / clear
# ---------------------------------------------------------------------------


def test_goal_pause_flips_status(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "a concrete test fixture goal")
    cmd_goal(a, "pause")
    st = load_state(tmp_path)
    assert st is not None
    assert st.status == "paused"


def test_goal_resume_from_paused(tmp_path: Path):
    a = _StubAgent(tmp_path, max_turns=20)
    cmd_goal(a, "a concrete test fixture goal")
    cmd_goal(a, "pause")
    cmd_goal(a, "resume")
    st = load_state(tmp_path)
    assert st is not None
    assert st.status == "active"
    # paused → active doesn't bump max_turns
    assert st.max_turns == 20


def test_goal_resume_from_exhausted_bumps_cap(tmp_path: Path):
    """The anti-runaway behaviour: resume after exhaustion adds
    cfg.goal_max_turns to max_turns — keeping turns_taken visible."""
    save_state(
        tmp_path,
        GoalState(text="x", status="exhausted", turns_taken=25, max_turns=25),
    )
    a = _StubAgent(tmp_path, max_turns=25)
    cmd_goal(a, "resume")
    st = load_state(tmp_path)
    assert st is not None
    assert st.status == "active"
    assert st.max_turns == 50
    assert st.turns_taken == 25  # not reset


def test_goal_clear_removes_both_files(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "a concrete test fixture goal")
    assert (tmp_path / "goal.txt").exists()
    cmd_goal(a, "clear")
    assert not (tmp_path / "goal.txt").exists()
    assert load_state(tmp_path) is None


def test_goal_clear_when_absent_is_noop(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "clear")  # nothing to clear → not an error
    assert a.reload_called == 1  # reload still called (defensive)


# ---------------------------------------------------------------------------
# /goal show / status
# ---------------------------------------------------------------------------


def test_goal_status_shows_when_set(tmp_path: Path, capsys):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "ship the migration verify command")
    cmd_goal(a, "status")
    out = capsys.readouterr().out
    assert "ship the migration verify command" in out
    assert "active" in out


def test_goal_bare_alias_for_status(tmp_path: Path, capsys):
    """Bare /goal == /goal status."""
    a = _StubAgent(tmp_path)
    cmd_goal(a, "ship the migration verify command")
    cmd_goal(a, "")
    out = capsys.readouterr().out
    assert "ship the migration verify command" in out


# ---------------------------------------------------------------------------
# /subgoal
# ---------------------------------------------------------------------------


def test_subgoal_add(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "ship the migration verify command")
    cmd_subgoal(a, "write the tests")
    cmd_subgoal(a, "update the docs")
    st = load_state(tmp_path)
    assert st is not None
    assert [sg.text for sg in st.subgoals] == ["write the tests", "update the docs"]
    assert all(not sg.done for sg in st.subgoals)


def test_subgoal_done_marks_first_pending(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "ship the migration verify command")
    cmd_subgoal(a, "first")
    cmd_subgoal(a, "second")
    cmd_subgoal(a, "done")
    st = load_state(tmp_path)
    assert st is not None
    assert st.subgoals[0].done is True
    assert st.subgoals[1].done is False
    # Second /subgoal done flips the next pending one.
    cmd_subgoal(a, "done")
    st = load_state(tmp_path)
    assert st.subgoals[1].done is True


def test_subgoal_done_when_all_done_is_noop(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "a concrete test fixture goal")
    cmd_subgoal(a, "one")
    cmd_subgoal(a, "done")
    cmd_subgoal(a, "done")  # already all done
    st = load_state(tmp_path)
    assert st is not None
    assert st.subgoals[0].done is True


def test_subgoal_requires_goal(tmp_path: Path):
    """/subgoal without /goal first → no state file is created.
    The error message goes through athena.ui which doesn't route
    through stdio so we don't assert on capture; the durable
    contract is "no state file" — testable."""
    a = _StubAgent(tmp_path)
    cmd_subgoal(a, "premature")
    assert load_state(tmp_path) is None


# ---------------------------------------------------------------------------
# Invariant block rendering
# ---------------------------------------------------------------------------


def test_invariant_block_includes_subgoals_and_contract():
    """T5-07.4 — format_for_system_prompt with a state object
    renders subgoals (with ✓/• markers) and the sentinel
    contract."""
    st = GoalState(
        text="ship feature X",
        subgoals=[
            Subgoal("write tests", done=True),
            Subgoal("update docs"),
        ],
    )
    block = format_for_system_prompt("ship feature X", state=st)
    assert "ship feature X" in block
    assert "Subgoals" in block
    assert "✓ write tests" in block
    assert "• update docs" in block
    assert "GOAL ACHIEVED" in block
    assert "GOAL BLOCKED" in block


def test_invariant_block_no_subgoals_block_when_none():
    """A state with no subgoals doesn't render an empty
    Subgoals: section. The contract still renders."""
    st = GoalState(text="x")
    block = format_for_system_prompt("x", state=st)
    assert "Subgoals" not in block
    assert "GOAL ACHIEVED" in block


def test_invariant_block_no_state_is_legacy_shape():
    """No state object → just goal text + header, like before
    T5-07. Back-compat for callers that don't yet pass state."""
    block = format_for_system_prompt("ship it")
    assert "ship it" in block
    assert "GOAL ACHIEVED" not in block
    assert "Subgoals" not in block
