"""Board projection + board_show tool tests (T6-06.3).

Two surfaces tested:

  - ``project_board(store, ...)`` — pure projection function
    over the store. Pinned: column ordering, per-column
    sort by store-order, workspace + goal_id filters, empty
    columns present even when empty.

  - ``board_show()`` — model-callable tool. Returns the
    payload as JSON; uses the same TaskStore the
    TaskCreate / TaskUpdate / TaskList tools share (the
    single-store invariant).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.tasks.board import (
    board_show,
    column_counts,
    project_board,
)
from athena.tasks.model import TaskStore
from athena.tools import task as task_mod


# ---------------------------------------------------------------------------
# project_board
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(path=tmp_path / "tasks.json")


def test_board_projection_columns(tmp_path: Path):
    """All four columns present (even empty), tasks land in the
    right column, sorted by their store-recorded order."""
    s = _make_store(tmp_path)
    t1 = s.create(title="A", workspace="/ws")
    t2 = s.create(title="B", workspace="/ws")
    t3 = s.create(title="C", workspace="/ws")
    # Move A → doing, C → done. B stays in todo.
    s.update(t1.id, status="doing")
    s.update(t3.id, status="done")

    cols = project_board(s, workspace="/ws")
    assert set(cols.keys()) == {"todo", "doing", "blocked", "done"}
    assert [c["title"] for c in cols["todo"]] == ["B"]
    assert [c["title"] for c in cols["doing"]] == ["A"]
    assert cols["blocked"] == []  # empty column still present
    assert [c["title"] for c in cols["done"]] == ["C"]


def test_board_projection_preserves_order_within_column(tmp_path: Path):
    s = _make_store(tmp_path)
    for title in ("first", "second", "third"):
        s.create(title=title, workspace="/ws")
    cols = project_board(s, workspace="/ws")
    assert [c["title"] for c in cols["todo"]] == ["first", "second", "third"]


def test_board_projection_card_shape(tmp_path: Path):
    """The card dict matches the documented shape — id /
    title / goal_id / order / note / parent_id / created_at /
    updated_at."""
    s = _make_store(tmp_path)
    t = s.create(
        title="card", workspace="/ws", goal_id="g1",
        note="some detail",
    )
    cols = project_board(s, workspace="/ws")
    card = cols["todo"][0]
    assert card["id"] == t.id
    assert card["title"] == "card"
    assert card["goal_id"] == "g1"
    assert card["parent_id"] is None
    assert card["order"] == t.order
    assert card["note"] == "some detail"
    assert isinstance(card["created_at"], float)
    assert isinstance(card["updated_at"], float)


def test_board_filter_by_workspace(tmp_path: Path):
    """workspace filter isolates one project's cards."""
    s = _make_store(tmp_path)
    s.create(title="A1", workspace="/proj/a")
    s.create(title="B1", workspace="/proj/b")

    cols_a = project_board(s, workspace="/proj/a")
    assert [c["title"] for c in cols_a["todo"]] == ["A1"]
    cols_b = project_board(s, workspace="/proj/b")
    assert [c["title"] for c in cols_b["todo"]] == ["B1"]


def test_board_filter_by_goal(tmp_path: Path):
    """goal_id filter isolates a single goal's subgoal-cards."""
    s = _make_store(tmp_path)
    s.create(title="solo", workspace="/ws")
    s.create(title="g1-a", workspace="/ws", goal_id="g1")
    s.create(title="g1-b", workspace="/ws", goal_id="g1")
    s.create(title="g2-a", workspace="/ws", goal_id="g2")

    cols = project_board(s, workspace="/ws", goal_id="g1")
    titles = [c["title"] for c in cols["todo"]]
    assert titles == ["g1-a", "g1-b"]


def test_board_filter_workspace_and_goal_compose(tmp_path: Path):
    s = _make_store(tmp_path)
    s.create(title="A-g1", workspace="/a", goal_id="g1")
    s.create(title="B-g1", workspace="/b", goal_id="g1")
    s.create(title="A-solo", workspace="/a")

    cols = project_board(s, workspace="/a", goal_id="g1")
    assert [c["title"] for c in cols["todo"]] == ["A-g1"]


def test_column_counts(tmp_path: Path):
    s = _make_store(tmp_path)
    t1 = s.create(title="a", workspace="/ws")
    s.create(title="b", workspace="/ws")
    s.update(t1.id, status="doing")

    cols = project_board(s, workspace="/ws")
    counts = column_counts(cols)
    assert counts == {"todo": 1, "doing": 1, "blocked": 0, "done": 0}


def test_board_empty_store(tmp_path: Path):
    """A fresh empty store → every column present + empty."""
    s = _make_store(tmp_path)
    cols = project_board(s, workspace="/ws")
    assert all(cols[c] == [] for c in ("todo", "doing", "blocked", "done"))


# ---------------------------------------------------------------------------
# board_show tool
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_task_store(monkeypatch, tmp_path: Path):
    """Each tool-test gets a fresh task-store rooted in tmp_path.
    Mirrors the task-tool test fixture so board_show reads the
    same store backing TaskCreate."""
    cfg = SimpleNamespace(
        task_store_path=str(tmp_path / "tasks.json"),
        profile="default",
    )
    monkeypatch.setattr("athena.config.load_config", lambda: cfg)
    monkeypatch.setattr(
        "athena.config.profile_dir", lambda profile: tmp_path / "profile"
    )
    task_mod._reset_for_tests()

    from athena.tools import file_ops

    file_ops._WORKSPACE = tmp_path / "ws"
    yield
    task_mod._reset_for_tests()


def test_board_show_returns_columns():
    """board_show returns JSON with the documented shape:
    workspace, goal_id, counts, columns."""
    task_mod.TaskCreate(subject="alpha", description="...")
    task_mod.TaskCreate(subject="beta", description="...")
    payload = json.loads(board_show())
    assert "workspace" in payload
    assert payload["goal_id"] is None
    assert "counts" in payload
    assert set(payload["columns"].keys()) == {"todo", "doing", "blocked", "done"}
    todo_titles = [c["title"] for c in payload["columns"]["todo"]]
    assert "alpha" in todo_titles
    assert "beta" in todo_titles


def test_board_show_reads_same_store_as_task_tools():
    """The SINGLE-STORE invariant at the tool level: board_show
    sees tasks created by TaskCreate. No parallel list."""
    out = task_mod.TaskCreate(subject="shared", description="...")
    task_id = out.split()[1]
    payload = json.loads(board_show())
    titles = [c["title"] for c in payload["columns"]["todo"]]
    assert "shared" in titles
    # And the id matches.
    ids = [c["id"] for c in payload["columns"]["todo"]]
    assert task_id in ids


def test_board_show_filter_by_goal_id():
    """board_show with a goal_id filter returns only that
    goal's cards. The task-tool path doesn't expose goal_id
    today (T6-06.4 wires the goal-loop projection that does)
    — here we exercise the filter via the store directly."""
    task_mod.TaskCreate(subject="solo", description="...")
    # Plant a goal-tagged task via the store (the goal-loop
    # projection in T6-06.4 will be the production path).
    store = task_mod._resolve_store()
    from athena.tools import file_ops

    store.create(
        title="goal-card",
        workspace=str(file_ops._WORKSPACE),
        goal_id="my-goal",
    )

    payload = json.loads(board_show(goal_id="my-goal"))
    titles = [c["title"] for c in payload["columns"]["todo"]]
    assert titles == ["goal-card"]


def test_board_show_status_moves_card():
    """Move a card via TaskUpdate (in_progress → doing column)
    and verify board_show reflects it."""
    out = task_mod.TaskCreate(subject="mover", description="...")
    task_id = out.split()[1]

    task_mod.TaskUpdate(taskId=task_id, status="in_progress")
    payload = json.loads(board_show())
    doing = [c["title"] for c in payload["columns"]["doing"]]
    todo = [c["title"] for c in payload["columns"]["todo"]]
    assert "mover" in doing
    assert "mover" not in todo


def test_board_show_empty_returns_empty_columns():
    """A fresh empty store → board_show returns the columns
    dict with every column empty + counts all 0."""
    payload = json.loads(board_show())
    assert payload["counts"] == {"todo": 0, "doing": 0, "blocked": 0, "done": 0}
    for col in ("todo", "doing", "blocked", "done"):
        assert payload["columns"][col] == []
