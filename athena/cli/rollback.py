"""Shared helpers for ``athena skill diff|rollback`` and
``athena memory diff|rollback``.

Both verbs follow the same shape:

1. Resolve the target name to a path on disk (skill dir or memory file).
2. Find the most-recent snapshot covering that path (or load a
   specific snapshot id when ``--to`` is provided).
3. For ``diff``: extract the snapshot's copy of the target to a
   tempdir, run ``difflib.unified_diff`` against the live file,
   print it. For ``rollback``: show that diff, prompt y/n
   (skipped with ``-y``), call ``SnapshotStore.restore()`` filtered
   to the target. After restore, append an audit record so the
   rollback itself is recorded.
"""

from __future__ import annotations

import difflib
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..provenance import FOREGROUND, get_current_write_origin
from ..safety.audit import MutationRecord, now_iso, sha_of_file
from ..safety.context import get_audit_log, get_snapshot_store
from ..safety.snapshots import Snapshot, SnapshotStore


class RollbackError(RuntimeError):
    """Raised by the helper when the rollback can't proceed (no
    snapshot found, target missing, snapshot has no matching member)."""


def _resolve_snapshot(
    store: SnapshotStore,
    target: Path,
    snapshot_id: str | None,
) -> Snapshot:
    if snapshot_id is not None:
        snaps = [s for s in store.list_snapshots() if s.snapshot_id == snapshot_id]
        if not snaps:
            raise RollbackError(f"no snapshot with id {snapshot_id!r}")
        return snaps[0]
    snap = store.find_most_recent_for(target)
    if snap is None:
        raise RollbackError(f"no snapshots cover {target} — nothing to roll back to")
    return snap


def _extract_member_to_tempdir(
    snap: Snapshot,
    target: Path,
    relative_to: Path,
) -> Path | None:
    """Extract the tarball member corresponding to ``target`` to a
    tempdir. Returns the extracted file path, or None if no member
    matched."""
    try:
        rel = target.resolve().relative_to(relative_to)
    except ValueError:
        return None
    member_name = rel.as_posix()
    with tarfile.open(snap.tarball_path, "r:gz") as tf:
        try:
            member = tf.getmember(member_name)
        except KeyError:
            return None
        dest = Path(tempfile.mkdtemp(prefix="athena-rollback-"))
        tf.extract(member, path=str(dest))
    return dest / member_name


def render_diff(before: str, after: str, label_before: str, label_after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=label_before,
        tofile=label_after,
    )
    return "".join(lines)


def diff_target(
    target: Path,
    *,
    snapshot_id: str | None = None,
    relative_to: Path | None = None,
) -> str:
    """Return the unified diff between the snapshot's copy of
    ``target`` and the live file. Raises :class:`RollbackError` if
    no usable snapshot is found."""
    store = get_snapshot_store()
    snap = _resolve_snapshot(store, target, snapshot_id)
    rel_root = relative_to or store.relative_to
    extracted = _extract_member_to_tempdir(snap, target, rel_root)
    if extracted is None or not extracted.exists():
        raise RollbackError(f"snapshot {snap.snapshot_id} does not include {target}")
    before = extracted.read_text(encoding="utf-8", errors="replace")
    after = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    return render_diff(
        before,
        after,
        label_before=f"{snap.snapshot_id}:{extracted.name}",
        label_after=f"current:{target.name}",
    )


def rollback_target(
    target: Path,
    *,
    tool_name: str,
    snapshot_id: str | None = None,
    confirm: Callable[[str], bool] | None = None,
    relative_to: Path | None = None,
) -> dict[str, Any]:
    """Roll the live file at ``target`` back to the snapshot copy.

    Writes a MutationRecord (``tool_name=<arg>``) after the restore
    so the rollback itself is auditable. Returns a summary dict.
    """
    store = get_snapshot_store()
    audit = get_audit_log()
    snap = _resolve_snapshot(store, target, snapshot_id)

    rel_root = relative_to or store.relative_to
    sha_before = sha_of_file(target)
    diff = diff_target(target, snapshot_id=snap.snapshot_id, relative_to=rel_root)

    if confirm is not None:
        approved = confirm(diff)
        if not approved:
            return {"status": "aborted", "snapshot_id": snap.snapshot_id}

    restored = store.restore(
        snap,
        path_filter=target,
        confirm=lambda _: True,
    )
    sha_after = sha_of_file(target)
    audit.append(
        MutationRecord(
            timestamp=now_iso(),
            write_origin=get_current_write_origin() or FOREGROUND,
            session_id=None,
            parent_session_id=None,
            tool_name=tool_name,
            tool_call_id="",
            path=str(target),
            snapshot_id=snap.snapshot_id,
            sha_before=sha_before,
            sha_after=sha_after,
            byte_delta=(
                (target.stat().st_size if target.exists() else 0) - (len(diff.encode("utf-8")) * 0)
            ),
        )
    )
    return {
        "status": "restored",
        "snapshot_id": snap.snapshot_id,
        "restored_paths": [str(p) for p in restored],
    }


def confirm_via_stdio(diff_text: str) -> bool:
    """Default confirm callback for CLI: prints the diff and asks
    y/N on stdin."""
    if not diff_text.strip():
        sys.stdout.write("(no differences between snapshot and current)\n")
        return False
    sys.stdout.write(diff_text)
    sys.stdout.write("\nProceed with rollback? [y/N] ")
    sys.stdout.flush()
    line = sys.stdin.readline()
    return line.strip().lower() in ("y", "yes")
