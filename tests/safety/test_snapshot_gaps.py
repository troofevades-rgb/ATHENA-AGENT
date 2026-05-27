"""Gaps in the SnapshotStore test coverage.

``tests/safety/test_snapshot_store.py`` covers happy-path round-trip,
filtering, pin/unpin, count-based pruning, and age-based pruning.
These tests fill the gaps that bite during actual recovery:

  * Byte-budget pruning (retention_bytes) — totally uncovered. If a
    burst of large captures fills the disk, this is what saves it.
  * Sidecar JSON corruption — partial writes, schema drift, manual
    edits. ``_load_sidecar`` swallows JSONDecodeError silently;
    confirm that's visible to the operator (not crashing).
  * Tarball missing but sidecar present — list_snapshots still
    returns it (the metadata is queryable). The right time to fail
    is on restore.
  * Sidecar present but referring to a nonexistent tarball path —
    don't crash list/restore enumeration.
  * Restore re-creates files that were deleted after snapshot —
    this is the actual "undo skill_delete" recovery path.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pytest

from athena.provenance import (
    CURATOR,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety.snapshots import SnapshotError, SnapshotStore


@pytest.fixture
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(
        root=tmp_path / "snaps",
        relative_to=tmp_path,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _make_skill(workspace: Path, name: str, body: str = "v1") -> Path:
    skill = workspace / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\n---\n\n{body}\n", encoding="utf-8",
    )
    return skill


def _take_snapshot(store: SnapshotStore, paths: list[Path]):
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate(paths, tool_name="test") as s:
            return s
    finally:
        reset_current_write_origin(token)


# ---------------------------------------------------------------------------
# Byte-budget pruning
# ---------------------------------------------------------------------------


def test_prune_respects_retention_bytes(tmp_path: Path) -> None:
    """retention_bytes is the safety valve: when count + age leave a
    fat backlog, this caps disk usage. A bug here means runaway
    snapshot growth can fill the user's home partition unnoticed.

    Strategy: make a store with retention_bytes set to fit ~2 snapshots
    of our test data; create 5; verify prune brings total under budget."""
    import secrets
    store = SnapshotStore(
        root=tmp_path / "snaps",
        retention_days=99999,
        retention_count=99999,
        retention_bytes=2000,  # tight — forces eviction
        relative_to=tmp_path,
    )
    skill = _make_skill(tmp_path, "demo", "v0")
    snaps = []
    token = set_current_write_origin(CURATOR)
    try:
        for _ in range(5):
            # Use incompressible random hex so gzip can't collapse our
            # carefully-distinct payloads into nothing
            (skill / "SKILL.md").write_text(
                secrets.token_hex(800), encoding="utf-8",
            )
            time.sleep(1.05)  # distinct second so snapshot IDs differ
            with store.snapshot_and_mutate([skill], tool_name="test") as s:
                snaps.append(s)
    finally:
        reset_current_write_origin(token)

    # Verify we DID create multiple distinct snapshots over budget
    assert len({s.snapshot_id for s in snaps}) >= 4, (
        "snapshots collapsed by content addressing; test setup bad"
    )
    total_before = sum(s.tarball_path.stat().st_size for s in snaps if s.tarball_path.exists())
    assert total_before > 2000, (
        f"test invalid: total bytes {total_before} already under budget"
    )

    summary = store.prune()

    # Total must now be under (or at) retention_bytes
    surviving = list((tmp_path / "snaps").rglob("*.tar.gz"))
    total_after = sum(p.stat().st_size for p in surviving)
    assert total_after <= 2000, (
        f"prune left {total_after} bytes on disk; budget was 2000. "
        f"retention_bytes is not enforced"
    )
    assert summary["removed"] >= 1, (
        f"prune removed nothing despite over-budget; summary={summary}"
    )


def test_prune_byte_budget_never_evicts_pinned(tmp_path: Path) -> None:
    """retention_bytes is a hard ceiling, but pinned snapshots survive
    even when that means staying over budget. Operators rely on this
    when they pin a forensically-important capture."""
    import secrets
    store = SnapshotStore(
        root=tmp_path / "snaps",
        retention_days=99999,
        retention_count=99999,
        retention_bytes=500,  # tiny — anything triggers eviction
        relative_to=tmp_path,
    )
    skill = _make_skill(tmp_path, "demo")
    token = set_current_write_origin(CURATOR)
    snaps = []
    try:
        for _ in range(3):
            (skill / "SKILL.md").write_text(
                secrets.token_hex(400), encoding="utf-8",
            )
            time.sleep(1.05)
            with store.snapshot_and_mutate([skill], tool_name="test") as s:
                snaps.append(s)
    finally:
        reset_current_write_origin(token)

    # Pin the OLDEST (which would normally be evicted first)
    oldest = snaps[0]
    assert store.pin(oldest.snapshot_id)

    store.prune()

    # The pinned tarball is still on disk
    assert oldest.tarball_path.exists(), (
        "byte-budget pruning evicted a pinned snapshot — should be unkillable"
    )


# ---------------------------------------------------------------------------
# Sidecar corruption / missing tarball resilience
# ---------------------------------------------------------------------------


def test_list_snapshots_skips_corrupt_sidecar(
    store: SnapshotStore, workspace: Path,
) -> None:
    """A partially-written sidecar (interrupted disk write, manual
    edit gone wrong) must NOT break ``list_snapshots`` for everyone
    else. The corrupt one drops out silently; the rest enumerate."""
    skill = _make_skill(workspace, "alpha")
    good = _take_snapshot(store, [skill])

    # Plant a corrupt sidecar in the same date directory
    bad_path = good.sidecar_path.parent / "9999-deadbeef-curator.json"
    bad_path.write_text("{this is { not json", encoding="utf-8")

    snaps = store.list_snapshots()
    ids = [s.snapshot_id for s in snaps]
    assert good.snapshot_id in ids, "good snapshot vanished from listing"
    # Corrupt one is silently dropped (not listed)
    assert "9999-deadbeef-curator" not in ids, (
        "corrupt sidecar surfaced as a snapshot; _load_sidecar isn't filtering"
    )


def test_list_snapshots_skips_sidecar_missing_required_field(
    store: SnapshotStore, workspace: Path,
) -> None:
    """A sidecar with valid JSON but missing required fields (e.g.
    schema drift from an older version) must also drop out silently
    rather than KeyError out of the enumeration."""
    skill = _make_skill(workspace, "alpha")
    good = _take_snapshot(store, [skill])

    # Plant a sidecar with valid JSON but missing 'snapshot_id'
    bad_path = good.sidecar_path.parent / "1234-cafe1234-curator.json"
    bad_path.write_text(
        json.dumps({"paths": [], "created_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )

    snaps = store.list_snapshots()
    ids = [s.snapshot_id for s in snaps]
    assert good.snapshot_id in ids
    assert len([i for i in ids if i.startswith("1234-")]) == 0


def test_list_snapshots_still_returns_record_when_tarball_missing(
    store: SnapshotStore, workspace: Path,
) -> None:
    """If someone deletes the .tar.gz manually but leaves the sidecar,
    the metadata is still queryable (you can see the snapshot
    existed, when, by what tool). The failure mode shifts to
    restore time."""
    skill = _make_skill(workspace, "alpha")
    snap = _take_snapshot(store, [skill])

    # Delete the tarball but keep the sidecar
    snap.tarball_path.unlink()

    snaps = store.list_snapshots()
    found = next((s for s in snaps if s.snapshot_id == snap.snapshot_id), None)
    assert found is not None, (
        "snapshot metadata vanished because the tarball was deleted; "
        "users lose forensic visibility on cleanup mishaps"
    )
    # Restore on this snapshot must raise SnapshotError, NOT swallow
    with pytest.raises(SnapshotError, match="tarball missing"):
        store.restore(found, dest_root=workspace, confirm=lambda _: True)


# ---------------------------------------------------------------------------
# Restore as recovery: deleted-file restoration (the skill_delete-undo path)
# ---------------------------------------------------------------------------


def test_restore_recreates_a_file_deleted_after_snapshot(
    store: SnapshotStore, workspace: Path,
) -> None:
    """The actual recovery scenario when a user wants to undo a
    ``skill_delete``: the file is gone from the live tree, but the
    snapshot has it. Restore must recreate the file at its original
    path with its original content."""
    skill = _make_skill(workspace, "doomed", "important content")
    original_bytes = (skill / "SKILL.md").read_bytes()
    snap = _take_snapshot(store, [skill])

    # Simulate skill_delete: blow away the whole tree
    import shutil
    shutil.rmtree(skill)
    assert not skill.exists()

    restored = store.restore(snap, dest_root=workspace, confirm=lambda _: True)
    assert restored, "restore returned no files for a non-empty snapshot"
    assert skill.exists()
    assert (skill / "SKILL.md").exists()
    assert (skill / "SKILL.md").read_bytes() == original_bytes


def test_restore_does_not_touch_files_outside_snapshot(
    store: SnapshotStore, workspace: Path,
) -> None:
    """Restoration must be SCOPED to what was actually snapshotted.
    A sibling file the user created AFTER the snapshot must survive
    a restore intact — otherwise restore is a destructive operation
    masquerading as an undo."""
    skill_a = _make_skill(workspace, "alpha", "a-content")
    snap = _take_snapshot(store, [skill_a])

    # User then creates a NEW skill that wasn't in the snapshot
    skill_b = _make_skill(workspace, "beta", "b-content")
    b_bytes = (skill_b / "SKILL.md").read_bytes()

    store.restore(snap, dest_root=workspace, confirm=lambda _: True)

    # skill_b is untouched
    assert skill_b.exists()
    assert (skill_b / "SKILL.md").read_bytes() == b_bytes


# ---------------------------------------------------------------------------
# Snapshot of a path that doesn't exist (e.g. skill_create's pre-state)
# ---------------------------------------------------------------------------


def test_snapshot_of_nonexistent_path_does_not_crash(
    store: SnapshotStore, workspace: Path,
) -> None:
    """skill_create's snapshot captures the soon-to-exist directory
    BEFORE creation — so the path may not exist yet. Must not raise."""
    ghost = workspace / "skills" / "not-yet-created"
    # ghost does not exist
    snap = _take_snapshot(store, [ghost])
    # Snapshot is still recorded — the audit trail wants the
    # attempt visible
    assert snap.tarball_path.exists()
    # And listed
    assert any(s.snapshot_id == snap.snapshot_id for s in store.list_snapshots())


# ---------------------------------------------------------------------------
# Idempotency: identical content → same snapshot_id (collapse)
# ---------------------------------------------------------------------------


def test_two_snapshots_of_identical_state_in_same_second_collapse(
    store: SnapshotStore, workspace: Path,
) -> None:
    """If a curator runs twice within one second touching the same
    unchanged tree, the second snapshot must collapse to the first.
    Without this, idle curators with high cadence balloon the
    snapshot store."""
    skill = _make_skill(workspace, "static")
    snap_a = _take_snapshot(store, [skill])
    snap_b = _take_snapshot(store, [skill])

    assert snap_a.snapshot_id == snap_b.snapshot_id, (
        "identical content in same second produced distinct IDs; "
        "collapse-by-content is broken"
    )
    # Only one tarball on disk
    tars = list(snap_a.tarball_path.parent.glob("*.tar.gz"))
    assert len(tars) == 1
