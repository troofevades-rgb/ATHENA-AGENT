"""Helpers that combine snapshot + audit into one call site.

The pattern at every mutation site is::

    sha_before = sha_of_file(path)
    with snapshot_and_record(paths, tool_name=..., session_id=...) as ctx:
        # ... do mutation ...
        ctx.record(path)

Where ``ctx.record`` writes the MutationRecord after capturing
``sha_after`` and ``byte_delta``. Keeps the per-call boilerplate
small without leaking the snapshot/audit details into the mutation
modules.
"""
from __future__ import annotations

import contextlib
import dataclasses
from pathlib import Path
from typing import Iterable, Iterator

from ..provenance import get_current_write_origin
from .audit import (
    MutationAuditLog,
    MutationRecord,
    now_iso,
    sha_of_file,
)
from .context import get_audit_log, get_snapshot_store
from .snapshots import Snapshot, SnapshotStore


@dataclasses.dataclass
class MutationContext:
    snapshot: Snapshot
    audit: MutationAuditLog
    tool_name: str
    tool_call_id: str | None
    session_id: str | None
    parent_session_id: str | None
    # Lazy: each call to record() captures the current sha + byte_delta.
    sha_before_by_path: dict[str, str | None] = dataclasses.field(default_factory=dict)

    def record(self, path: Path) -> None:
        """Emit one MutationRecord for ``path``. Should be called
        once after the mutation completes, per path that changed."""
        path = Path(path)
        path_str = str(path)
        sha_before = self.sha_before_by_path.get(path_str)
        sha_after = sha_of_file(path)
        try:
            after_bytes = path.stat().st_size if path.exists() and path.is_file() else 0
        except OSError:
            after_bytes = 0
        before_bytes = self.sha_before_by_path.get(path_str + ":bytes", 0)
        try:
            before_bytes_int = int(before_bytes)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            before_bytes_int = 0
        byte_delta = after_bytes - before_bytes_int
        self.audit.append(MutationRecord(
            timestamp=now_iso(),
            write_origin=get_current_write_origin(),
            session_id=self.session_id,
            parent_session_id=self.parent_session_id,
            tool_name=self.tool_name,
            tool_call_id=self.tool_call_id or "",
            path=path_str,
            snapshot_id=self.snapshot.snapshot_id,
            sha_before=sha_before,
            sha_after=sha_after,
            byte_delta=byte_delta,
        ))


@contextlib.contextmanager
def snapshot_and_record(
    paths: Iterable[Path],
    *,
    tool_name: str,
    session_id: str | None = None,
    tool_call_id: str | None = None,
    parent_session_id: str | None = None,
    profile_dir: Path | None = None,
    snapshot_store: SnapshotStore | None = None,
    audit_log: MutationAuditLog | None = None,
) -> Iterator[MutationContext]:
    """Take a snapshot of ``paths``, capture sha_before per path,
    then yield a context the caller fills via :meth:`MutationContext.record`.

    The snapshot is *always* taken — every mutation gets a rollback
    point, regardless of write_origin. The audit record is written
    when the caller invokes ``ctx.record(path)``.
    """
    paths = tuple(Path(p) for p in paths)
    store = snapshot_store or get_snapshot_store(profile_dir)
    audit = audit_log or get_audit_log(profile_dir)

    sha_before_by_path: dict[str, str | None] = {}
    for p in paths:
        # Hash the leaf file (e.g. SKILL.md) when path is a dir.
        if p.is_dir():
            skill_md = p / "SKILL.md"
            if skill_md.exists():
                sha_before_by_path[str(skill_md)] = sha_of_file(skill_md)
                try:
                    sha_before_by_path[str(skill_md) + ":bytes"] = (
                        skill_md.stat().st_size  # type: ignore[assignment]
                    )
                except OSError:
                    pass
        else:
            sha_before_by_path[str(p)] = sha_of_file(p)
            try:
                sha_before_by_path[str(p) + ":bytes"] = (
                    p.stat().st_size if p.exists() else 0  # type: ignore[assignment]
                )
            except OSError:
                pass

    with store.snapshot_and_mutate(
        paths,
        session_id=session_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        parent_session_id=parent_session_id,
    ) as snapshot:
        ctx = MutationContext(
            snapshot=snapshot,
            audit=audit,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            session_id=session_id,
            parent_session_id=parent_session_id,
            sha_before_by_path=sha_before_by_path,
        )
        yield ctx
