"""Persisted task-store tests (T6-06.1).

Pins the model contract: create + update + list/filter +
archive, plus the single-store invariant the board + the goal
loop both rely on (tasks and goal subgoals live in the same
backing dict, distinguished by goal_id).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.tasks.model import (
    Task,
    TaskStore,
    default_task_store_path,
)


def _store(tmp_path: Path) -> TaskStore:
    return TaskStore(path=tmp_path / "tasks.json")


# ---------------------------------------------------------------------------
# create / update / delete
# ---------------------------------------------------------------------------


def test_task_create_persists(tmp_path: Path):
    """Create a task in one store instance, reopen, see it."""
    s = _store(tmp_path)
    t = s.create(title="first task", workspace="/ws")
    assert t.id.startswith("t-")
    assert t.title == "first task"
    assert t.status == "todo"
    assert t.workspace == "/ws"

    # Fresh store reading the same file sees the task.
    s2 = TaskStore(path=tmp_path / "tasks.json")
    back = s2.get(t.id)
    assert back is not None
    assert back.title == "first task"
    assert back.status == "todo"


def test_task_create_rejects_empty_title(tmp_path: Path):
    s = _store(tmp_path)
    with pytest.raises(ValueError):
        s.create(title="   ")


def test_task_create_rejects_bad_status(tmp_path: Path):
    s = _store(tmp_path)
    with pytest.raises(ValueError):
        s.create(title="x", status="pending")  # not a canonical name


def test_task_update_status(tmp_path: Path):
    """Status moves: todo → doing → done. Each transition
    re-orders the task to the end of its new column."""
    s = _store(tmp_path)
    t1 = s.create(title="A", workspace="/ws")
    t2 = s.create(title="B", workspace="/ws")
    assert t1.order == 0
    assert t2.order == 1

    # Move t1 to doing.
    updated = s.update(t1.id, status="doing")
    assert updated.status == "doing"
    # t1 is the only task in the doing column → order 0.
    assert updated.order == 0
    # B is still order 1 in todo (unaffected).
    assert s.get(t2.id).order == 1


def test_task_update_unknown_id_raises(tmp_path: Path):
    s = _store(tmp_path)
    with pytest.raises(KeyError):
        s.update("does-not-exist", status="done")


def test_task_update_partial_fields(tmp_path: Path):
    """Title-only update doesn't change status; status-only
    doesn't change title."""
    s = _store(tmp_path)
    t = s.create(title="orig", workspace="/ws", note="orig note")
    updated = s.update(t.id, title="renamed")
    assert updated.title == "renamed"
    assert updated.status == "todo"
    assert updated.note == "orig note"


def test_task_delete(tmp_path: Path):
    s = _store(tmp_path)
    t = s.create(title="bye", workspace="/ws")
    assert s.delete(t.id) is True
    assert s.get(t.id) is None
    # Idempotent — re-delete returns False.
    assert s.delete(t.id) is False


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_list_filters_by_workspace_and_goal(tmp_path: Path):
    """list() filters cleanly on workspace, goal_id, and
    status — independently and together."""
    s = _store(tmp_path)
    s.create(title="ws-a regular", workspace="/proj/a")
    s.create(title="ws-b regular", workspace="/proj/b")
    s.create(title="ws-a goal", workspace="/proj/a", goal_id="goal-1")
    s.create(title="ws-a goal-2", workspace="/proj/a", goal_id="goal-2")

    # Workspace filter only.
    a_only = s.list(workspace="/proj/a")
    assert {t.title for t in a_only} == {"ws-a regular", "ws-a goal", "ws-a goal-2"}

    # Goal filter only.
    g1 = s.list(goal_id="goal-1")
    assert [t.title for t in g1] == ["ws-a goal"]

    # Combined.
    a_g1 = s.list(workspace="/proj/a", goal_id="goal-1")
    assert [t.title for t in a_g1] == ["ws-a goal"]


def test_list_filters_by_status(tmp_path: Path):
    s = _store(tmp_path)
    t1 = s.create(title="t1", workspace="/ws")
    s.create(title="t2", workspace="/ws")
    s.update(t1.id, status="doing")

    doing = s.list(workspace="/ws", status="doing")
    assert [t.title for t in doing] == ["t1"]
    todo = s.list(workspace="/ws", status="todo")
    assert [t.title for t in todo] == ["t2"]


def test_list_sort_order(tmp_path: Path):
    """Returned list sorts by (status column, order). Used by
    the board projection so a column read is just a slice."""
    s = _store(tmp_path)
    # Create in interleaved status; the sort is by status
    # column first, then order within.
    a = s.create(title="A", workspace="/ws")
    s.update(a.id, status="done")
    b = s.create(title="B", workspace="/ws")
    s.update(b.id, status="doing")
    c = s.create(title="C", workspace="/ws")
    s.update(c.id, status="doing")

    out = s.list(workspace="/ws")
    # Columns: todo (none) → doing [B, C] → blocked (none) → done [A]
    assert [t.title for t in out] == ["B", "C", "A"]


# ---------------------------------------------------------------------------
# Single-store invariant
# ---------------------------------------------------------------------------


def test_one_store_for_tasks_and_subgoals(tmp_path: Path):
    """The store backs BOTH regular tasks and goal subgoals.
    goal_id is the only thing that distinguishes them; they
    share the same on-disk file. The single-store invariant
    is what makes the board / goal-subgoal projections agree."""
    s = _store(tmp_path)
    regular = s.create(title="cleanup", workspace="/ws")
    subgoal = s.create(
        title="define schema", workspace="/ws", goal_id="my-goal"
    )

    # Both visible to list().
    all_tasks = s.list(workspace="/ws")
    assert {t.id for t in all_tasks} == {regular.id, subgoal.id}

    # goal_id filter isolates the subgoal.
    only_goal = s.list(workspace="/ws", goal_id="my-goal")
    assert [t.id for t in only_goal] == [subgoal.id]

    # Disk file is one JSON list, both rows present.
    raw = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in raw}
    assert ids == {regular.id, subgoal.id}


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def test_archive_done_after_days(tmp_path: Path):
    """Done tasks older than the threshold are removed from the
    live list; recent ones stay. older_than_days<=0 is a no-op."""
    s = _store(tmp_path)
    old_done = s.create(title="old", workspace="/ws")
    s.update(old_done.id, status="done")
    # Backdate.
    s.get(old_done.id).updated_at = time.time() - (60 * 86400)

    recent_done = s.create(title="recent", workspace="/ws")
    s.update(recent_done.id, status="done")

    still_doing = s.create(title="active", workspace="/ws")
    s.update(still_doing.id, status="doing")

    # Threshold 30d: archives only the old one.
    n = s.archive_done(older_than_days=30.0)
    assert n == 1
    live = {t.id for t in s.list(workspace="/ws")}
    assert old_done.id not in live
    assert recent_done.id in live
    assert still_doing.id in live


def test_archive_zero_threshold_is_noop(tmp_path: Path):
    """older_than_days<=0 → 0 archived. Don't accidentally
    archive everything by passing 0."""
    s = _store(tmp_path)
    t = s.create(title="x", workspace="/ws")
    s.update(t.id, status="done")
    assert s.archive_done(older_than_days=0) == 0
    assert s.archive_done(older_than_days=-1) == 0


def test_clear_removes_live_tasks(tmp_path: Path):
    s = _store(tmp_path)
    for i in range(3):
        s.create(title=f"t{i}", workspace="/ws")
    assert s.clear() == 3
    assert s.list() == []


# ---------------------------------------------------------------------------
# Persistence + recovery
# ---------------------------------------------------------------------------


def test_corrupt_file_starts_empty(tmp_path: Path):
    """A malformed JSON file → start empty (logged), next save
    overwrites cleanly. Doesn't crash session start."""
    path = tmp_path / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json {{{", encoding="utf-8")
    s = TaskStore(path=path)
    assert s.list() == []
    # Next create overwrites the bad file.
    s.create(title="fresh", workspace="/ws")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert len(raw) == 1


def test_default_task_store_path_uses_cfg_override(tmp_path: Path):
    cfg = SimpleNamespace(task_store_path=str(tmp_path / "explicit.json"))
    p = default_task_store_path(cfg, tmp_path / "profile")
    assert p == tmp_path / "explicit.json"


def test_default_task_store_path_falls_back_to_profile_dir(tmp_path: Path):
    cfg = SimpleNamespace(task_store_path=None)
    p = default_task_store_path(cfg, tmp_path / "profile")
    assert p == tmp_path / "profile" / "tasks" / "tasks.json"
