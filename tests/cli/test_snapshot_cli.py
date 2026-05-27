"""End-to-end tests for ``athena snapshot {list,show,pin,unpin,prune}``.

Zero coverage today. This CLI is the user's only window into the
snapshot store for audit and recovery. If it breaks, the user can
inspect the disk manually but the recovery story is gone.

We drive the CLI through its ``main(argv)`` entry point and assert
on the bytes that hit stdout / stderr.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from athena.cli import snapshot as snapshot_cli
from athena.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety import context as safety_context
from athena.safety.snapshots import SnapshotStore


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Replace ``get_snapshot_store`` with one rooted at tmp_path so
    the CLI under test cannot reach the developer's real
    ~/.athena/snapshots."""
    safety_context.reset_for_tests()
    store = SnapshotStore(
        root=tmp_path / "snapshots",
        relative_to=tmp_path,
    )

    def _get(*args, **kw):
        return store

    monkeypatch.setattr(snapshot_cli, "get_snapshot_store", _get)
    yield store
    safety_context.reset_for_tests()


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


def _snap(store: SnapshotStore, paths, origin: str = CURATOR):
    token = set_current_write_origin(origin)
    try:
        with store.snapshot_and_mutate(paths, tool_name="test") as s:
            return s
    finally:
        reset_current_write_origin(token)


def _run(argv, capsys) -> tuple[int, str, str]:
    """Invoke the CLI; return (exit_code, stdout, stderr)."""
    capsys.readouterr()  # clear
    code = snapshot_cli.main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_empty_store_prints_friendly_message(
    isolated_store, capsys,
) -> None:
    code, out, err = _run(["list"], capsys)
    assert code == 0
    assert "no snapshots" in out.lower()
    assert err == ""


def test_list_shows_all_snapshots_newest_first(
    isolated_store, workspace, capsys,
) -> None:
    import time
    skill = _make_skill(workspace, "alpha")
    older = _snap(isolated_store, [skill])
    time.sleep(1.05)  # different second so created_at differs
    (skill / "SKILL.md").write_text("v2", encoding="utf-8")
    newer = _snap(isolated_store, [skill])

    code, out, _ = _run(["list"], capsys)
    assert code == 0
    # Both IDs in output
    assert older.snapshot_id in out
    assert newer.snapshot_id in out
    # Newer comes first
    assert out.index(newer.snapshot_id) < out.index(older.snapshot_id)


def test_list_json_format_is_parseable(
    isolated_store, workspace, capsys,
) -> None:
    """--json must emit a valid JSON array that downstream scripts
    can parse. Required for ops automation."""
    skill = _make_skill(workspace, "alpha")
    snap = _snap(isolated_store, [skill])

    code, out, _ = _run(["list", "--json"], capsys)
    assert code == 0
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["snapshot_id"] == snap.snapshot_id
    assert "created_at" in data[0]
    assert "paths" in data[0]


def test_list_write_origin_filter(isolated_store, workspace, capsys) -> None:
    """--write-origin restricts to one origin. Critical when the
    user is hunting for a specific curator vs background_review
    mutation."""
    skill = _make_skill(workspace, "alpha")
    cur_snap = _snap(isolated_store, [skill], origin=CURATOR)
    rev_snap = _snap(isolated_store, [skill], origin=BACKGROUND_REVIEW)

    code, out, _ = _run(["list", "--write-origin", "curator"], capsys)
    assert code == 0
    assert cur_snap.snapshot_id in out
    assert rev_snap.snapshot_id not in out


def test_list_limit_caps_rows(isolated_store, workspace, capsys) -> None:
    import time
    skill = _make_skill(workspace, "alpha")
    snaps = []
    for i in range(4):
        (skill / "SKILL.md").write_text(f"v{i}", encoding="utf-8")
        time.sleep(1.05)
        snaps.append(_snap(isolated_store, [skill]))

    code, out, _ = _run(["list", "--limit", "2", "--json"], capsys)
    assert code == 0
    data = json.loads(out)
    assert len(data) == 2
    # The two newest
    assert data[0]["snapshot_id"] == snaps[-1].snapshot_id
    assert data[1]["snapshot_id"] == snaps[-2].snapshot_id


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_dumps_sidecar_and_tar_listing(
    isolated_store, workspace, capsys,
) -> None:
    skill = _make_skill(workspace, "alpha", "content")
    snap = _snap(isolated_store, [skill])

    code, out, _ = _run(["show", snap.snapshot_id], capsys)
    assert code == 0
    # Sidecar section
    assert snap.snapshot_id in out
    assert "tar contents:" in out
    # The SKILL.md member should appear in the tar listing
    assert "SKILL.md" in out


def test_show_unknown_id_exits_nonzero(
    isolated_store, capsys,
) -> None:
    code, out, err = _run(["show", "no-such-snapshot"], capsys)
    assert code == 1
    assert "no snapshot" in err.lower()


# ---------------------------------------------------------------------------
# pin / unpin
# ---------------------------------------------------------------------------


def test_pin_then_unpin_round_trip(
    isolated_store, workspace, capsys,
) -> None:
    skill = _make_skill(workspace, "alpha")
    snap = _snap(isolated_store, [skill])

    code, out, _ = _run(["pin", snap.snapshot_id], capsys)
    assert code == 0
    assert "pinned" in out.lower()

    # The persisted state reflects the pin
    fresh = isolated_store.list_snapshots()
    pinned = next(s for s in fresh if s.snapshot_id == snap.snapshot_id)
    assert pinned.pinned is True

    code, out, _ = _run(["unpin", snap.snapshot_id], capsys)
    assert code == 0
    assert "unpinned" in out.lower()

    fresh = isolated_store.list_snapshots()
    unpinned = next(s for s in fresh if s.snapshot_id == snap.snapshot_id)
    assert unpinned.pinned is False


def test_pin_unknown_id_exits_nonzero(isolated_store, capsys) -> None:
    code, out, err = _run(["pin", "no-such-snapshot"], capsys)
    assert code == 1
    assert "no snapshot" in err.lower()


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def test_prune_dry_run_does_not_remove(
    isolated_store, workspace, capsys,
) -> None:
    """``--dry-run`` must print the plan without touching the
    filesystem. If this regresses to actually deleting, an
    operator's investigatory prune-list becomes a real prune."""
    import datetime as dt
    skill = _make_skill(workspace, "alpha")
    snap = _snap(isolated_store, [skill])

    # Force it to be "old" so it would be a candidate
    sidecar_payload = json.loads(snap.sidecar_path.read_text(encoding="utf-8"))
    sidecar_payload["created_at"] = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=180)
    ).isoformat()
    snap.sidecar_path.write_text(
        json.dumps(sidecar_payload, default=str), encoding="utf-8",
    )

    before_tar_exists = snap.tarball_path.exists()
    assert before_tar_exists

    code, out, _ = _run(["prune", "--dry-run"], capsys)
    assert code == 0
    assert "dry-run" in out.lower()

    # Tarball still on disk — dry-run is non-destructive
    assert snap.tarball_path.exists(), (
        "--dry-run removed a snapshot — must be read-only"
    )


def test_prune_actually_removes_eligible_snapshots(
    isolated_store, workspace, capsys,
) -> None:
    """The destructive path: stale snapshots beyond retention_days
    get evicted on a real prune."""
    import datetime as dt
    skill = _make_skill(workspace, "alpha")
    snap = _snap(isolated_store, [skill])

    # Force it to be far past the retention horizon
    payload = json.loads(snap.sidecar_path.read_text(encoding="utf-8"))
    payload["created_at"] = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=180)
    ).isoformat()
    snap.sidecar_path.write_text(json.dumps(payload, default=str), encoding="utf-8")

    code, out, _ = _run(["prune"], capsys)
    assert code == 0
    m = re.search(r"removed=(\d+)", out)
    assert m, f"prune output missing removed= counter: {out!r}"
    assert int(m.group(1)) >= 1, (
        f"expected to evict the stale snapshot; output={out!r}"
    )
    assert not snap.tarball_path.exists()
    assert not snap.sidecar_path.exists()
