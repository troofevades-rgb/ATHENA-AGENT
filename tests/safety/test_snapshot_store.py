"""SnapshotStore — content-addressed tarball pre-state preservation."""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pytest

from athena.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety.snapshots import (
    SnapshotError,
    SnapshotStore,
    _path_covers,
)


@pytest.fixture
def store(snapshot_root: Path, tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(
        root=snapshot_root,
        relative_to=tmp_path,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Tree the tests treat as their 'home'. Skills + memory live
    under here; the store's ``relative_to`` is set to ``tmp_path``
    so tarball arcnames stay portable."""
    return tmp_path


def _write_skill_tree(workspace: Path, name: str = "demo") -> Path:
    """Build a small skill tree under workspace and return its root."""
    skill_root = workspace / "skills" / name
    skill_root.mkdir(parents=True, exist_ok=True)
    (skill_root / "SKILL.md").write_text(
        f"---\nname: {name}\n---\n\noriginal body\n",
        encoding="utf-8",
    )
    refs = skill_root / "references"
    refs.mkdir(exist_ok=True)
    (refs / "background.md").write_text(
        "original reference content",
        encoding="utf-8",
    )
    return skill_root


# ---- round-trip ---------------------------------------------------


def test_snapshot_round_trip_bit_exact(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    """Snapshot a tree, mutate, restore — files identical to pre-state."""
    skill = _write_skill_tree(workspace)
    original_body = (skill / "SKILL.md").read_bytes()
    original_ref = (skill / "references" / "background.md").read_bytes()

    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate(
            [skill],
            tool_name="skill_manage",
            session_id="s1",
        ) as snap:
            # Mutate.
            (skill / "SKILL.md").write_text("after consolidation\n", "utf-8")
            (skill / "references" / "background.md").unlink()
    finally:
        reset_current_write_origin(token)

    # State changed.
    assert (skill / "SKILL.md").read_text() == "after consolidation\n"
    assert not (skill / "references" / "background.md").exists()

    # Restore.
    restored = store.restore(snap, dest_root=workspace, confirm=lambda _: True)
    assert restored  # at least one file came back

    # Bit-exact.
    assert (skill / "SKILL.md").read_bytes() == original_body
    assert (skill / "references" / "background.md").read_bytes() == original_ref


def test_snapshot_persists_when_mutation_raises(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    """The snapshot survives a failed mutation — that's the audit
    trail."""
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(BACKGROUND_REVIEW)
    captured: dict = {}
    try:
        try:
            with store.snapshot_and_mutate(
                [skill],
                tool_name="skill_manage",
            ) as snap:
                captured["snap"] = snap
                raise RuntimeError("simulated mutation failure")
        except RuntimeError:
            pass
    finally:
        reset_current_write_origin(token)

    snap = captured["snap"]
    assert snap.tarball_path.exists()
    assert snap.sidecar_path.exists()


# ---- content addressing -------------------------------------------


def test_same_pre_state_same_second_collapses(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    """Identical pre-state under the same write_origin at the same
    timestamp produces one tarball on disk, not two."""
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap1:
            pass
        # Re-snapshot the unchanged tree within the same second.
        with store.snapshot_and_mutate([skill]) as snap2:
            pass
    finally:
        reset_current_write_origin(token)

    # Same ID → same tarball path.
    if snap1.snapshot_id == snap2.snapshot_id:
        assert snap1.tarball_path == snap2.tarball_path
    # In any case, identical content hash component.
    assert snap1.snapshot_id.split("-", 1)[1] == snap2.snapshot_id.split("-", 1)[1]


def test_different_origin_changes_id(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap_curator:
            pass
    finally:
        reset_current_write_origin(token)

    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        with store.snapshot_and_mutate([skill]) as snap_review:
            pass
    finally:
        reset_current_write_origin(token)

    assert snap_curator.write_origin == "curator"
    assert snap_review.write_origin == "background_review"
    assert snap_curator.snapshot_id != snap_review.snapshot_id


# ---- sidecar completeness ----------------------------------------


def test_sidecar_carries_every_field(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate(
            [skill],
            session_id="s-1",
            tool_name="skill_manage",
            tool_call_id="call-7",
            parent_session_id="p-9",
        ) as snap:
            pass
    finally:
        reset_current_write_origin(token)

    payload = json.loads(snap.sidecar_path.read_text(encoding="utf-8"))
    assert payload["snapshot_id"] == snap.snapshot_id
    assert payload["session_id"] == "s-1"
    assert payload["tool_name"] == "skill_manage"
    assert payload["tool_call_id"] == "call-7"
    assert payload["parent_session_id"] == "p-9"
    assert payload["write_origin"] == "curator"
    assert payload["created_at"]
    assert payload["athena_version"]
    assert "paths" in payload


def test_sidecar_paths_resolved_to_absolute(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    """Tarball arcnames are relative; sidecar paths are absolute so
    audit consumers can identify the original location."""
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)
    payload = json.loads(snap.sidecar_path.read_text(encoding="utf-8"))
    assert str(skill.resolve()) in payload["paths"]


# ---- list + find -------------------------------------------------


def test_list_snapshots_returns_newest_first(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill_a = _write_skill_tree(workspace, "a")
    skill_b = _write_skill_tree(workspace, "b")
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill_a]) as snap_a:
            pass
        # Ensure timestamps differ (the store uses unix-second
        # precision, so a small sleep guarantees different ids).
        time.sleep(1.1)
        with store.snapshot_and_mutate([skill_b]) as snap_b:
            pass
    finally:
        reset_current_write_origin(token)
    snaps = store.list_snapshots()
    assert snaps[0].snapshot_id == snap_b.snapshot_id
    assert snaps[1].snapshot_id == snap_a.snapshot_id


def test_list_filters_by_write_origin(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]):
            pass
    finally:
        reset_current_write_origin(token)
    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        time.sleep(1.1)
        with store.snapshot_and_mutate([skill]):
            pass
    finally:
        reset_current_write_origin(token)
    only_curator = store.list_snapshots(write_origin_filter="curator")
    only_review = store.list_snapshots(write_origin_filter="background_review")
    assert len(only_curator) == 1
    assert len(only_review) == 1
    assert only_curator[0].write_origin == "curator"


def test_list_filters_by_path(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill_a = _write_skill_tree(workspace, "alpha")
    skill_b = _write_skill_tree(workspace, "beta")
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill_a]):
            pass
        time.sleep(1.1)
        with store.snapshot_and_mutate([skill_b]):
            pass
    finally:
        reset_current_write_origin(token)
    just_alpha = store.list_snapshots(path_filter=skill_a)
    assert len(just_alpha) == 1
    assert just_alpha[0].paths[0] == skill_a.resolve()


def test_list_limit(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        for i in range(3):
            (skill / "SKILL.md").write_text(f"version-{i}", encoding="utf-8")
            time.sleep(1.05)
            with store.snapshot_and_mutate([skill]):
                pass
    finally:
        reset_current_write_origin(token)
    assert len(store.list_snapshots()) == 3
    assert len(store.list_snapshots(limit=2)) == 2


def test_find_most_recent_for_skill_root(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)
    found = store.find_most_recent_for(skill)
    assert found is not None
    assert found.snapshot_id == snap.snapshot_id


def test_find_most_recent_for_nested_path_uses_ancestor(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    """find_most_recent_for(skill_md_file) returns the snapshot that
    captured the parent dir."""
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)
    nested = skill / "SKILL.md"
    found = store.find_most_recent_for(nested)
    assert found is not None
    assert found.snapshot_id == snap.snapshot_id


def test_find_returns_none_for_unrelated_path(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    _ = _write_skill_tree(workspace, "alpha")
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([workspace / "skills" / "alpha"]):
            pass
    finally:
        reset_current_write_origin(token)
    other = workspace / "unrelated" / "thing.md"
    assert store.find_most_recent_for(other) is None


# ---- pinning ----------------------------------------------------


def test_pin_then_unpin(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)
    assert store.pin(snap.snapshot_id) is True
    loaded = store._load_sidecar(snap.sidecar_path)
    assert loaded.pinned is True
    assert store.unpin(snap.snapshot_id) is True
    loaded = store._load_sidecar(snap.sidecar_path)
    assert loaded.pinned is False


def test_pin_unknown_returns_false(store: SnapshotStore) -> None:
    assert store.pin("does-not-exist") is False


# ---- restore + path_filter --------------------------------------


def test_restore_path_filter_only_extracts_subtree(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    """Filter the restore to a specific file under the snapshot."""
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)
    # Wipe both files.
    (skill / "SKILL.md").write_text("clobbered", encoding="utf-8")
    (skill / "references" / "background.md").write_text("clobbered", "utf-8")

    restored = store.restore(
        snap,
        path_filter=skill / "SKILL.md",
        dest_root=workspace,
        confirm=lambda _: True,
    )
    # Only SKILL.md restored; references/background.md still
    # clobbered.
    assert (skill / "SKILL.md").read_text().startswith("---\nname:")
    assert (skill / "references" / "background.md").read_text() == "clobbered"
    assert any(str(p).endswith("SKILL.md") for p in restored)


def test_restore_confirm_false_aborts(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)
    (skill / "SKILL.md").write_text("changed", encoding="utf-8")

    restored = store.restore(
        snap,
        dest_root=workspace,
        confirm=lambda _: False,
    )
    assert restored == []
    # Live filesystem untouched.
    assert (skill / "SKILL.md").read_text() == "changed"


def test_restore_missing_tarball_raises(
    store: SnapshotStore,
    workspace: Path,
) -> None:
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)
    snap.tarball_path.unlink()
    with pytest.raises(SnapshotError, match="tarball missing"):
        store.restore(snap, dest_root=workspace, confirm=lambda _: True)


# ---- prune --------------------------------------------------------


def test_prune_respects_retention_days(
    snapshot_root: Path,
    workspace: Path,
) -> None:
    """Snapshots older than retention_days get pruned; younger ones
    keep. Pinned ones always survive."""
    store = SnapshotStore(
        root=snapshot_root,
        retention_days=30,
        relative_to=workspace,
    )
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap_recent:
            pass
    finally:
        reset_current_write_origin(token)

    # Synthesize an old snapshot by editing the sidecar's created_at.
    payload = json.loads(snap_recent.sidecar_path.read_text(encoding="utf-8"))
    # Make a copy so we still have a recent one for comparison.
    aged_id = snap_recent.snapshot_id + "-aged"
    aged_sidecar = snap_recent.sidecar_path.parent / f"{aged_id}.json"
    aged_tar = snap_recent.sidecar_path.parent / f"{aged_id}.tar.gz"
    aged_tar.write_bytes(snap_recent.tarball_path.read_bytes())
    aged_payload = dict(payload)
    aged_payload["snapshot_id"] = aged_id
    aged_payload["created_at"] = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=120)
    ).isoformat()
    aged_sidecar.write_text(json.dumps(aged_payload, default=str), encoding="utf-8")

    summary = store.prune()
    assert summary["removed"] == 1
    assert summary["kept"] == 1
    assert not aged_tar.exists()
    assert snap_recent.tarball_path.exists()


def test_prune_skips_pinned(
    snapshot_root: Path,
    workspace: Path,
) -> None:
    store = SnapshotStore(
        root=snapshot_root,
        retention_days=30,
        relative_to=workspace,
    )
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    try:
        with store.snapshot_and_mutate([skill]) as snap:
            pass
    finally:
        reset_current_write_origin(token)

    # Age + pin it.
    payload = json.loads(snap.sidecar_path.read_text(encoding="utf-8"))
    payload["created_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=120)).isoformat()
    payload["pinned"] = True
    snap.sidecar_path.write_text(json.dumps(payload, default=str), encoding="utf-8")

    summary = store.prune()
    assert summary["removed"] == 0
    assert summary["pinned"] == 1
    assert snap.tarball_path.exists()


def test_prune_respects_count(
    snapshot_root: Path,
    workspace: Path,
) -> None:
    """retention_count=2 + 4 snapshots → prune 2 oldest unpinned."""
    store = SnapshotStore(
        root=snapshot_root,
        retention_days=99999,  # disable age
        retention_count=2,
        relative_to=workspace,
    )
    skill = _write_skill_tree(workspace)
    token = set_current_write_origin(CURATOR)
    snaps = []
    try:
        for i in range(4):
            (skill / "SKILL.md").write_text(f"v{i}", encoding="utf-8")
            time.sleep(1.05)
            with store.snapshot_and_mutate([skill]) as s:
                snaps.append(s)
    finally:
        reset_current_write_origin(token)

    summary = store.prune()
    assert summary["removed"] == 2
    assert summary["kept"] == 2


# ---- _path_covers helper ----------------------------------------


def test_path_covers_identical() -> None:
    p = Path("/x/y")
    assert _path_covers(p, p) is True


def test_path_covers_ancestor() -> None:
    assert _path_covers(Path("/a"), Path("/a/b/c.md")) is True


def test_path_covers_unrelated() -> None:
    assert _path_covers(Path("/a"), Path("/b/c")) is False


def test_path_covers_sibling() -> None:
    assert _path_covers(Path("/a/b"), Path("/a/c")) is False
