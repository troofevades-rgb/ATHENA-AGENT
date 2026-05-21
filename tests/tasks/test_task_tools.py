"""TaskCreate / TaskUpdate / TaskList tool surface tests (T6-06.2).

Two contracts pinned:

  1. The tool API and the strings it returns are byte-identical
     to the previous in-memory implementation. The agent doesn't
     see a behaviour change — just persistence appears.
  2. Across a fresh ``_resolve_store()`` (which happens between
     processes), tasks survive — the persistence the T6-06.1
     model brought is now visible at the tool surface.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.tools import task as task_mod


@pytest.fixture(autouse=True)
def _clean_module(monkeypatch, tmp_path: Path):
    """Each test gets a fresh task store rooted in tmp_path so
    state never bleeds between tests."""
    cfg = SimpleNamespace(
        task_store_path=str(tmp_path / "tasks.json"),
        profile="default",
    )
    monkeypatch.setattr("athena.config.load_config", lambda: cfg)
    monkeypatch.setattr(
        "athena.config.profile_dir", lambda profile: tmp_path / "profile"
    )
    task_mod._reset_for_tests()

    # Workspace resolution reads file_ops._WORKSPACE — point it
    # at the tmp workspace so the tools tag tasks correctly.
    from athena.tools import file_ops

    file_ops._WORKSPACE = tmp_path / "ws"
    yield
    task_mod._reset_for_tests()


# ---------------------------------------------------------------------------
# API parity (pre-T6-06.2 behaviour)
# ---------------------------------------------------------------------------


def test_create_returns_legacy_string():
    """Return shape matches the pre-T6-06.2 contract:
    'Task <id> created: <subject>'. The id format changed from
    incrementing ints to t-<uuid12>; that's a visible change
    documented in the changelog."""
    out = task_mod.TaskCreate(subject="ship it", description="ship the thing")
    assert out.startswith("Task t-")
    assert "created: ship it" in out


def test_create_then_list_shows_the_task():
    task_mod.TaskCreate(subject="first", description="first task")
    listing = task_mod.TaskList()
    assert "first" in listing
    assert "[ ]" in listing  # pending → [ ]


def test_update_in_progress_then_completed():
    """Status flow uses the legacy external vocabulary:
    pending → in_progress → completed."""
    out = task_mod.TaskCreate(subject="work", description="work to do")
    tid = _extract_id(out)
    upd1 = task_mod.TaskUpdate(taskId=tid, status="in_progress")
    assert "status=in_progress" in upd1
    upd2 = task_mod.TaskUpdate(taskId=tid, status="completed")
    assert "status=completed" in upd2
    listing = task_mod.TaskList()
    assert "[x]" in listing


def test_update_invalid_status():
    out = task_mod.TaskCreate(subject="x", description="x")
    tid = _extract_id(out)
    bad = task_mod.TaskUpdate(taskId=tid, status="zarquon")
    assert bad.startswith("ERROR")


def test_update_unknown_task():
    out = task_mod.TaskUpdate(taskId="t-deadbeef", status="completed")
    assert out.startswith("ERROR")


def test_update_deleted_removes_task():
    out = task_mod.TaskCreate(subject="bye", description="bye")
    tid = _extract_id(out)
    del_out = task_mod.TaskUpdate(taskId=tid, status="deleted")
    assert "deleted" in del_out
    assert task_mod.TaskList() == "(no tasks)"


def test_list_empty_returns_legacy_string():
    assert task_mod.TaskList() == "(no tasks)"


def test_update_with_no_changes_short_circuits():
    """TaskUpdate with no fields beyond taskId reports 'no
    changes' rather than touching the store."""
    out = task_mod.TaskCreate(subject="x", description="x")
    tid = _extract_id(out)
    same = task_mod.TaskUpdate(taskId=tid)
    assert "no changes" in same


def test_update_subject_and_description():
    out = task_mod.TaskCreate(
        subject="old subject", description="old description"
    )
    tid = _extract_id(out)
    task_mod.TaskUpdate(taskId=tid, subject="new subject", description="new desc")
    listing = task_mod.TaskList()
    assert "new subject" in listing
    assert "new desc" in listing


# ---------------------------------------------------------------------------
# Persistence — the new behaviour T6-06.2 brings
# ---------------------------------------------------------------------------


def test_task_tool_now_persists(monkeypatch, tmp_path: Path):
    """A task created via the tool in one 'process' is visible
    after _reset_for_tests() simulates a restart. The persistence
    layer kicked in transparently — no API change."""
    out = task_mod.TaskCreate(subject="persist me", description="across reload")
    tid = _extract_id(out)

    # Simulate a restart by clearing the cached store.
    task_mod._reset_for_tests()

    # New store comes up fresh from disk; the task is there.
    listing = task_mod.TaskList()
    assert "persist me" in listing
    # And update still finds it.
    upd = task_mod.TaskUpdate(taskId=tid, status="completed")
    assert "status=completed" in upd


def test_workspace_scoping():
    """Tasks created in workspace A don't show up in workspace
    B's listing. The store separates them by the recorded
    workspace path."""
    from athena.tools import file_ops

    # Workspace A.
    file_ops._WORKSPACE = Path("/proj/a")
    task_mod._reset_for_tests()
    task_mod.TaskCreate(subject="A1", description="...")
    task_mod.TaskCreate(subject="A2", description="...")

    listing_a = task_mod.TaskList()
    assert "A1" in listing_a
    assert "A2" in listing_a

    # Workspace B — same process, switched cwd.
    file_ops._WORKSPACE = Path("/proj/b")
    task_mod._reset_for_tests()
    task_mod.TaskCreate(subject="B1", description="...")

    listing_b = task_mod.TaskList()
    assert "B1" in listing_b
    assert "A1" not in listing_b
    assert "A2" not in listing_b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_id(create_output: str) -> str:
    """Pull the id out of 'Task t-abc123def456 created: ...'."""
    parts = create_output.split()
    assert parts[0] == "Task"
    return parts[1]
