"""Goal-loop ↔ task store projection tests (T6-06.4).

The single-store invariant at the integration level:

  /subgoal <text>   →  creates a TaskStore row with goal_id set
  /subgoal done     →  flips the matching task's status to done
  /goal <new>       →  clears prior goal's subgoal-cards from store
  /goal clear       →  same — store is cleaned

The goal block's text rendering (system prompt) still reads
from GoalState.subgoals — the visible representation of the
plan to the model. But every subgoal mutation goes through the
store, so the board (board_show / athena board) and the goal's
view of subgoals can never disagree about what cards exist.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.commands.goal import cmd_goal, cmd_subgoal
from athena.goal.state import GoalState, load_state, save_state
from athena.tasks.model import TaskStore, default_task_store_path
from athena.tools import task as task_mod


class _StubAgent:
    """Minimum surface the goal commands touch."""

    def __init__(self, profile_dir: Path, *, workspace: Path | None = None):
        self._pdir = profile_dir
        self.cfg = SimpleNamespace(goal_max_turns=10)
        self.workspace = workspace
        self.reload_called = 0

    def _profile_dir(self):
        return self._pdir

    def reload_goal(self):
        self.reload_called += 1


@pytest.fixture(autouse=True)
def _store_in_tmp(monkeypatch, tmp_path: Path):
    """Reset the task-tool store + point athena.config.load_config
    at a tmp store_path so the projection writes don't leak."""
    cfg = SimpleNamespace(
        task_store_path=str(tmp_path / "tasks.json"),
        profile="default",
        goal_max_turns=10,
        board_auto_maintain=True,
    )
    monkeypatch.setattr("athena.config.load_config", lambda: cfg)
    monkeypatch.setattr(
        "athena.config.profile_dir", lambda profile: tmp_path / "profile_dir"
    )
    task_mod._reset_for_tests()
    yield
    task_mod._reset_for_tests()


def _store(tmp_path: Path) -> TaskStore:
    return TaskStore(path=tmp_path / "tasks.json")


# ---------------------------------------------------------------------------
# /subgoal creates a card with goal_id set
# ---------------------------------------------------------------------------


def test_subgoal_creates_task_with_goal_id(tmp_path: Path):
    """A /subgoal <text> command creates a TaskStore row with
    the goal's goal_id set — the projection write-through."""
    pdir = tmp_path / "profile"
    pdir.mkdir()
    agent = _StubAgent(pdir, workspace=tmp_path / "ws")
    cmd_goal(agent, "build a concrete test fixture thing")

    cmd_subgoal(agent, "design the schema")

    # Reload state to read goal_id.
    state = load_state(pdir)
    assert state is not None
    assert state.goal_id.startswith("g-")
    # And the Subgoal carries the task_id back-pointer.
    assert len(state.subgoals) == 1
    assert state.subgoals[0].task_id is not None

    # Store contains the matching row.
    store = _store(tmp_path)
    rows = store.list(goal_id=state.goal_id)
    assert len(rows) == 1
    assert rows[0].title == "design the schema"
    assert rows[0].goal_id == state.goal_id


def test_subgoal_done_moves_card_to_done(tmp_path: Path):
    """Completing a subgoal flips the matching task to done."""
    pdir = tmp_path / "profile"
    pdir.mkdir()
    agent = _StubAgent(pdir, workspace=tmp_path / "ws")
    cmd_goal(agent, "ship the migration verify command")
    cmd_subgoal(agent, "first")
    cmd_subgoal(agent, "second")

    state = load_state(pdir)
    rows_before = _store(tmp_path).list(goal_id=state.goal_id, status="todo")
    assert len(rows_before) == 2

    cmd_subgoal(agent, "done")
    state = load_state(pdir)
    assert state.subgoals[0].done is True
    assert state.subgoals[1].done is False

    # Store reflects: one done, one todo. Re-read via a fresh
    # TaskStore instance — the prior one's in-memory dict
    # doesn't auto-refresh from disk when other instances
    # write.
    fresh = _store(tmp_path)
    todo_after = fresh.list(goal_id=state.goal_id, status="todo")
    done_after = fresh.list(goal_id=state.goal_id, status="done")
    assert len(todo_after) == 1
    assert todo_after[0].title == "second"
    assert len(done_after) == 1
    assert done_after[0].title == "first"


# ---------------------------------------------------------------------------
# Single-store invariant
# ---------------------------------------------------------------------------


def test_one_store_no_parallel_lists(tmp_path: Path):
    """Two views of the same data must agree:

      - state.subgoals (the GoalState's in-memory list, the
        system-prompt rendering source)
      - store.list(goal_id=state.goal_id) (the board's source)

    Both come from the same writes. The single-store invariant
    means the board and the goal block can never disagree on
    what subgoals exist."""
    pdir = tmp_path / "profile"
    pdir.mkdir()
    agent = _StubAgent(pdir, workspace=tmp_path / "ws")
    cmd_goal(agent, "complete the test fixture objective")
    cmd_subgoal(agent, "alpha")
    cmd_subgoal(agent, "beta")
    cmd_subgoal(agent, "gamma")
    cmd_subgoal(agent, "done")  # alpha → done

    state = load_state(pdir)
    store = _store(tmp_path)

    # Same set of titles in both.
    state_titles = sorted(sg.text for sg in state.subgoals)
    store_titles = sorted(t.title for t in store.list(goal_id=state.goal_id))
    assert state_titles == store_titles == ["alpha", "beta", "gamma"]

    # Same done status in both.
    state_done = {sg.text for sg in state.subgoals if sg.done}
    store_done = {
        t.title for t in store.list(goal_id=state.goal_id, status="done")
    }
    assert state_done == store_done == {"alpha"}


def test_goal_replace_clears_prior_store_cards(tmp_path: Path):
    """A new /goal <text> drops the previous goal's subgoal-cards
    from the store — otherwise the board would accumulate stale
    cards from old goals."""
    pdir = tmp_path / "profile"
    pdir.mkdir()
    agent = _StubAgent(pdir, workspace=tmp_path / "ws")

    cmd_goal(agent, "the first concrete fixture goal")
    prior_state = load_state(pdir)
    cmd_subgoal(agent, "first subgoal")
    # Fresh store read — the prior in-memory instance doesn't
    # see writes that landed via task_mod._store's instance.
    assert len(_store(tmp_path).list(goal_id=prior_state.goal_id)) == 1

    # Replace with a new goal.
    cmd_goal(agent, "the second concrete fixture goal")
    new_state = load_state(pdir)
    assert new_state.goal_id != prior_state.goal_id
    # Previous goal's subgoal-cards are GONE.
    assert _store(tmp_path).list(goal_id=prior_state.goal_id) == []


def test_goal_clear_removes_store_cards(tmp_path: Path):
    """/goal clear drops every subgoal-card for that goal_id."""
    pdir = tmp_path / "profile"
    pdir.mkdir()
    agent = _StubAgent(pdir, workspace=tmp_path / "ws")
    cmd_goal(agent, "the concrete test fixture goal")
    cmd_subgoal(agent, "a subgoal")
    state = load_state(pdir)
    goal_id = state.goal_id

    cmd_goal(agent, "clear")
    store = _store(tmp_path)
    assert store.list(goal_id=goal_id) == []


# ---------------------------------------------------------------------------
# Workspace propagation
# ---------------------------------------------------------------------------


def test_subgoal_card_carries_workspace(tmp_path: Path):
    """The subgoal-card lands tagged with the agent's workspace
    so the board's workspace filter shows it correctly."""
    pdir = tmp_path / "profile"
    pdir.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    agent = _StubAgent(pdir, workspace=ws)
    cmd_goal(agent, "a concrete fixture goal here")
    cmd_subgoal(agent, "do thing")

    state = load_state(pdir)
    store = _store(tmp_path)
    rows = store.list(goal_id=state.goal_id)
    assert len(rows) == 1
    assert rows[0].workspace == str(ws)


# ---------------------------------------------------------------------------
# Auto-maintain nudge in the system prompt
# ---------------------------------------------------------------------------


def test_board_auto_maintain_nudge_in_system_prompt(tmp_path: Path):
    """When board_auto_maintain=True, the system prompt
    includes a section nudging the agent to keep the board
    current. When False, it doesn't."""
    from athena.prompts.system import build_system_prompt

    with_nudge = build_system_prompt(
        workspace=tmp_path,
        model="x",
        board_auto_maintain=True,
    )
    assert "Task board (auto-maintained)" in with_nudge
    assert "TaskCreate" in with_nudge

    without_nudge = build_system_prompt(
        workspace=tmp_path,
        model="x",
        board_auto_maintain=False,
    )
    assert "Task board (auto-maintained)" not in without_nudge
