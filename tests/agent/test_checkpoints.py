"""Tests for athena.agent.checkpoints (T3-03.3).

Build a real CheckpointManager against an actual SnapshotStore
(it's small and self-contained); the only stubbed dependency is
the audit log, which the manager creates a real one of by default
anyway. This way the tests cover the integration between manager
and SnapshotStore rather than testing against a parallel-universe
stub.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.agent.checkpoints import (
    CheckpointAuditLog,
    CheckpointManager,
    CheckpointNotFound,
    InFlightToolCallError,
    get_active_checkpoint_manager,
    restore_memory,
    restore_skills,
    set_active_checkpoint_manager,
    snapshot_memory,
    snapshot_skills,
    track_modified_file,
)
from athena.safety.snapshots import SnapshotStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    p = tmp_path / "profile"
    p.mkdir()
    return p


@pytest.fixture
def snapshot_store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(
        root=tmp_path / "fs_snapshots",
        relative_to=tmp_path,
    )


@pytest.fixture
def session_log(tmp_path: Path) -> Path:
    p = tmp_path / "session.jsonl"
    p.write_text(
        json.dumps({"role": "system", "content": "sys"})
        + "\n"
        + json.dumps({"role": "user", "content": "u1"})
        + "\n"
        + json.dumps({"role": "assistant", "content": "a1"})
        + "\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def manager(
    tmp_path: Path,
    workspace: Path,
    profile_dir: Path,
    snapshot_store: SnapshotStore,
    session_log: Path,
) -> CheckpointManager:
    return CheckpointManager(
        session_id="s1",
        session_log_path=session_log,
        checkpoint_dir=tmp_path / "checkpoints",
        snapshot_store=snapshot_store,
        profile_dir=profile_dir,
        workspace=workspace,
    )


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


def test_create_checkpoint_assigns_id_and_label(manager) -> None:
    cp = manager.create()
    assert cp.id.startswith("cp-")
    assert cp.label.startswith("checkpoint-")


def test_create_checkpoint_with_label(manager) -> None:
    cp = manager.create(label="before-refactor")
    assert cp.label == "before-refactor"


def test_create_checkpoint_persists_file(manager) -> None:
    cp = manager.create()
    cp_file = manager.checkpoint_dir / f"{cp.id}.json"
    assert cp_file.exists()
    loaded = json.loads(cp_file.read_text(encoding="utf-8"))
    assert loaded["id"] == cp.id


def test_create_checkpoint_captures_session_message_count(manager) -> None:
    cp = manager.create()
    assert cp.session_message_count == 3  # fixture has 3 lines


def test_create_checkpoint_captures_modified_files(manager, tmp_path) -> None:
    target = tmp_path / "modified.txt"
    target.write_text("hello", encoding="utf-8")
    manager.track_modified_file(target)
    cp = manager.create()
    assert cp.file_snapshot_id is not None


def test_create_resets_modification_tracking(manager, tmp_path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("hi", encoding="utf-8")
    manager.track_modified_file(f)
    manager.create()
    assert manager._tracked_modified_files == set()


def test_create_with_no_modified_files_has_no_file_snapshot(manager) -> None:
    cp = manager.create()
    assert cp.file_snapshot_id is None


def test_create_records_audit_event(manager) -> None:
    manager.create(label="audited")
    events = manager.audit_log.query(event_type="checkpoint")
    assert len(events) == 1
    assert "audited" in events[0]["summary"]


# ---------------------------------------------------------------------------
# list / find / purge
# ---------------------------------------------------------------------------


def test_list_returns_all_checkpoints(manager) -> None:
    manager.create(label="a")
    manager.create(label="b")
    cps = manager.list()
    assert len(cps) == 2
    assert sorted(c.label for c in cps) == ["a", "b"]


def test_find_by_label_or_id(manager) -> None:
    cp = manager.create(label="findable")
    assert manager._find("findable").id == cp.id
    assert manager._find(cp.id).id == cp.id
    assert manager._find("nope") is None


# ---------------------------------------------------------------------------
# rollback_to()
# ---------------------------------------------------------------------------


def test_rollback_to_truncates_session_log(manager) -> None:
    manager.create(label="early")
    # Add more messages after the checkpoint
    with open(manager.session_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"role": "user", "content": "u2"}) + "\n")
        f.write(json.dumps({"role": "assistant", "content": "a2"}) + "\n")
    assert manager._count_session_messages() == 5

    manager.rollback_to("early")
    # After rollback: 3 original + 1 synthetic marker = 4 lines.
    assert manager._count_session_messages() == 4
    last_line = manager.session_log_path.read_text(encoding="utf-8").splitlines()[-1]
    assert "rolled back" in last_line.lower()


def test_rollback_creates_pre_rollback_checkpoint(manager) -> None:
    manager.create(label="early")
    manager.rollback_to("early")
    pre_rollback = [c for c in manager.list() if c.label.startswith("pre-rollback-")]
    assert len(pre_rollback) == 1


def test_rollback_nonexistent_raises(manager) -> None:
    with pytest.raises(CheckpointNotFound):
        manager.rollback_to("does-not-exist")


def test_rollback_in_flight_tool_call_raises(manager) -> None:
    manager.create(label="early")
    manager.set_tool_call_in_flight(True)
    with pytest.raises(InFlightToolCallError):
        manager.rollback_to("early")
    manager.set_tool_call_in_flight(False)
    # After clearing the flag rollback should work again.
    manager.rollback_to("early")


def test_rollback_restores_files(manager, tmp_path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("version A", encoding="utf-8")
    manager.track_modified_file(target)
    manager.create(label="before-change")

    # Mutate the file after the checkpoint.
    target.write_text("version B", encoding="utf-8")

    manager.rollback_to("before-change")
    assert target.read_text(encoding="utf-8") == "version A"


def test_rollback_records_audit_event(manager) -> None:
    manager.create(label="early")
    manager.rollback_to("early")
    rollback_events = manager.audit_log.query(event_type="rollback")
    assert len(rollback_events) == 1
    assert "early" in rollback_events[0]["summary"]


def test_purge_pre_rollback_removes_auto_checkpoints(manager) -> None:
    manager.create(label="real-1")
    manager.rollback_to("real-1")  # creates pre-rollback-of-<id>
    assert any(c.label.startswith("pre-rollback-") for c in manager.list())
    removed = manager.purge_pre_rollback()
    assert removed >= 1
    assert not any(c.label.startswith("pre-rollback-") for c in manager.list())


# ---------------------------------------------------------------------------
# Skill / memory snapshot helpers
# ---------------------------------------------------------------------------


def test_snapshot_skills_returns_stable_token(tmp_path) -> None:
    """Snapshotting the same workspace twice returns the same token —
    content-addressed and deterministic."""
    workspace = tmp_path / "ws"
    skill_dir = workspace / ".athena" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("body", encoding="utf-8")

    snapshot_dir = tmp_path / "snaps"
    t1 = snapshot_skills(workspace, snapshot_dir)
    t2 = snapshot_skills(workspace, snapshot_dir)
    assert t1 == t2


def test_snapshot_skills_changes_after_mutation(tmp_path) -> None:
    workspace = tmp_path / "ws"
    skill_dir = workspace / ".athena" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "skill.md"
    skill_file.write_text("v1", encoding="utf-8")

    snapshot_dir = tmp_path / "snaps"
    t1 = snapshot_skills(workspace, snapshot_dir)
    skill_file.write_text("v2", encoding="utf-8")
    t2 = snapshot_skills(workspace, snapshot_dir)
    assert t1 != t2


def test_restore_skills_reverts_content(tmp_path) -> None:
    workspace = tmp_path / "ws"
    skill_dir = workspace / ".athena" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "skill.md"
    skill_file.write_text("original", encoding="utf-8")

    snapshot_dir = tmp_path / "snaps"
    token = snapshot_skills(workspace, snapshot_dir)

    skill_file.write_text("modified", encoding="utf-8")
    restored = restore_skills(token, snapshot_dir)
    assert restored >= 1
    assert skill_file.read_text(encoding="utf-8") == "original"


def test_restore_skills_idempotent_when_state_matches(tmp_path) -> None:
    workspace = tmp_path / "ws"
    skill_dir = workspace / ".athena" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("body", encoding="utf-8")
    snapshot_dir = tmp_path / "snaps"
    token = snapshot_skills(workspace, snapshot_dir)

    # State matches → nothing restored.
    assert restore_skills(token, snapshot_dir) == 0


def test_snapshot_memory_round_trip(tmp_path) -> None:
    profile = tmp_path / "profile"
    memory_dir = profile / "memory"
    memory_dir.mkdir(parents=True)
    entry = memory_dir / "thing.md"
    entry.write_text("first version", encoding="utf-8")

    snapshot_dir = tmp_path / "snaps"
    token = snapshot_memory(profile, snapshot_dir)
    entry.write_text("second version", encoding="utf-8")
    restored = restore_memory(token, snapshot_dir)
    assert restored == 1
    assert entry.read_text(encoding="utf-8") == "first version"


# ---------------------------------------------------------------------------
# ContextVar accessor + track_modified_file convenience
# ---------------------------------------------------------------------------


def test_active_manager_context_var(manager) -> None:
    assert get_active_checkpoint_manager() is None
    set_active_checkpoint_manager(manager)
    try:
        assert get_active_checkpoint_manager() is manager
    finally:
        set_active_checkpoint_manager(None)
    assert get_active_checkpoint_manager() is None


def test_track_modified_file_routes_to_active_manager(manager, tmp_path) -> None:
    f = tmp_path / "tracked.txt"
    f.write_text("x", encoding="utf-8")
    set_active_checkpoint_manager(manager)
    try:
        track_modified_file(f)
        assert f.resolve() in manager._tracked_modified_files
    finally:
        set_active_checkpoint_manager(None)


def test_track_modified_file_with_no_manager_is_noop(tmp_path) -> None:
    set_active_checkpoint_manager(None)
    # Should NOT raise.
    track_modified_file(tmp_path / "anything.txt")


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_audit_log_append_and_query(tmp_path) -> None:
    log = CheckpointAuditLog(tmp_path / "audit.jsonl")
    log.record(event_type="checkpoint", summary="cp1", data={"id": "1"})
    log.record(event_type="rollback", summary="rb1", data={"to": "1"})

    all_events = log.query()
    assert len(all_events) == 2

    cps = log.query(event_type="checkpoint")
    assert len(cps) == 1
    assert cps[0]["summary"] == "cp1"
