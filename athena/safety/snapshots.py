"""Content-addressed snapshots for agent-driven mutations.

Every write performed under a ``write_origin != "foreground"`` is
preceded by a tarball snapshot of the affected paths so the prior
state is recoverable. Snapshots are content-addressed (a hash of the
pre-mutation tarball) so identical pre-states collapse to the same
artifact — a curator that touches a skill ten times without changing
anything doesn't burn ten copies of disk.

Invariants:

- :meth:`SnapshotStore.snapshot_and_mutate` is the supported entry
  point for agent-driven writes. Direct file writes from
  ``write_origin != "foreground"`` code paths bypass the snapshot —
  the CI grep test from Phase 17.5 catches new code that does this.
- Snapshot creation is synchronous. If snapshotting fails the
  mutation fails — there's no fallback. Async snapshotting opens a
  window where the mutation succeeds and the snapshot is lost; that
  trade isn't acceptable for the forensic chain-of-custody use case
  this phase is built for.
- Snapshot IDs include a unix timestamp prefix so identical
  pre-states under the same write_origin at different moments
  produce distinct IDs (replay / audit needs ordering).

Storage layout:

    ~/.athena/snapshots/
      YYYY/MM/DD/
        <ts>-<sha[:12]>-<origin>.tar.gz
        <ts>-<sha[:12]>-<origin>.json     # sidecar
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import io
import json
import logging
import tarfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR
from ..provenance import get_current_write_origin

logger = logging.getLogger(__name__)


SNAPSHOT_ROOT = CONFIG_DIR / "snapshots"


@dataclasses.dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    paths: tuple[Path, ...]
    write_origin: str
    session_id: str | None
    tool_name: str | None
    tool_call_id: str | None
    athena_version: str
    parent_session_id: str | None
    created_at: dt.datetime
    tarball_path: Path
    sidecar_path: Path
    pinned: bool = False


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be created or restored."""


class SnapshotStore:
    """Manages the lifecycle of mutation snapshots under ``root``."""

    def __init__(
        self,
        root: Path = SNAPSHOT_ROOT,
        *,
        retention_days: int = 90,
        retention_count: int = 5_000,
        retention_bytes: int = 5 * 1024**3,
        relative_to: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.retention_days = retention_days
        self.retention_count = retention_count
        self.retention_bytes = retention_bytes
        # `relative_to` is the root for tar member names — defaults
        # to ``Path.home()`` so the tarball preserves the user's home
        # layout (and rollback restores into it). Tests inject
        # tmp_path so they don't accidentally clobber real files.
        self.relative_to = (relative_to or Path.home()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- snapshot + mutate -----------------------------------------

    @contextlib.contextmanager
    def snapshot_and_mutate(
        self,
        paths: Iterable[Path],
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        parent_session_id: str | None = None,
    ) -> Iterator[Snapshot]:
        """Context manager: snapshot ``paths``, then yield the
        :class:`Snapshot` to the caller's mutation code.

        If the caller raises inside the body, the snapshot is still
        kept on disk — the audit trail of attempted-and-failed
        mutations is exactly what makes recovery possible.

        The mutation itself is the caller's responsibility; this
        function only preserves the pre-state.
        """
        resolved = tuple(Path(p).resolve() for p in paths)
        snapshot = self._create_snapshot(
            resolved,
            session_id=session_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            parent_session_id=parent_session_id,
        )
        try:
            yield snapshot
        finally:
            # Snapshot persists regardless of whether mutation
            # succeeded. The audit log (Phase 17.4) records the
            # success/failure separately.
            pass

    # ---- internals ------------------------------------------------

    def _create_snapshot(
        self,
        paths: tuple[Path, ...],
        *,
        session_id: str | None,
        tool_name: str | None,
        tool_call_id: str | None,
        parent_session_id: str | None,
    ) -> Snapshot:
        write_origin = get_current_write_origin() or "foreground"
        now = dt.datetime.now(dt.timezone.utc)

        # Build tarball in memory first so we can hash before writing.
        # 1 MB skill trees compress + sha256 in well under 50ms; the
        # design budget allows for this.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for p in paths:
                if not p.exists():
                    continue
                # Member name: path relative to ``relative_to`` so
                # extraction is positional. ``Path.relative_to`` raises
                # if p isn't under relative_to; fall back to the bare
                # name in that case so we still record _something_.
                try:
                    arcname = p.relative_to(self.relative_to).as_posix()
                except ValueError:
                    arcname = p.name
                tf.add(p, arcname=arcname)
        tarball_bytes = buf.getvalue()
        sha = hashlib.sha256(tarball_bytes).hexdigest()[:12]
        snapshot_id = f"{int(now.timestamp())}-{sha}-{write_origin}"

        # snapshots/YYYY/MM/DD/<id>.tar.gz
        dated = self.root / now.strftime("%Y/%m/%d")
        dated.mkdir(parents=True, exist_ok=True)
        tarball_path = dated / f"{snapshot_id}.tar.gz"
        sidecar_path = dated / f"{snapshot_id}.json"

        if tarball_path.exists():
            # Same content under same timestamp under same origin —
            # idempotent. Return the existing record.
            existing = self._load_sidecar(sidecar_path)
            if existing is not None:
                return existing
            # Sidecar gone or corrupt; fall through and re-write.

        tarball_path.write_bytes(tarball_bytes)
        try:
            from athena import __version__ as athena_version
        except ImportError:  # pragma: no cover
            athena_version = "?"
        sidecar = {
            "snapshot_id": snapshot_id,
            "paths": [str(p) for p in paths],
            "write_origin": write_origin,
            "session_id": session_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "athena_version": athena_version,
            "parent_session_id": parent_session_id,
            "created_at": now.isoformat(),
            "pinned": False,
        }
        sidecar_path.write_text(
            json.dumps(sidecar, indent=2, default=str),
            encoding="utf-8",
        )

        return Snapshot(
            snapshot_id=snapshot_id,
            paths=paths,
            write_origin=write_origin,
            session_id=session_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            athena_version=athena_version,
            parent_session_id=parent_session_id,
            created_at=now,
            tarball_path=tarball_path,
            sidecar_path=sidecar_path,
            pinned=False,
        )

    def _load_sidecar(self, sidecar_path: Path) -> Snapshot | None:
        if not sidecar_path.exists():
            return None
        try:
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            paths = tuple(Path(p) for p in payload.get("paths") or ())
            created_at = dt.datetime.fromisoformat(payload["created_at"])
            tarball_path = sidecar_path.with_suffix(".tar.gz")
            # Some legacy / corrupt rows may use the old name.
            if not tarball_path.exists():
                tarball_path = sidecar_path.parent / (sidecar_path.stem + ".tar.gz")
            return Snapshot(
                snapshot_id=payload["snapshot_id"],
                paths=paths,
                write_origin=payload.get("write_origin", "foreground"),
                session_id=payload.get("session_id"),
                tool_name=payload.get("tool_name"),
                tool_call_id=payload.get("tool_call_id"),
                athena_version=payload.get("athena_version", "?"),
                parent_session_id=payload.get("parent_session_id"),
                created_at=created_at,
                tarball_path=tarball_path,
                sidecar_path=sidecar_path,
                pinned=bool(payload.get("pinned", False)),
            )
        except (KeyError, ValueError, TypeError):
            return None

    # ---- listing + search ----------------------------------------

    def list_snapshots(
        self,
        *,
        path_filter: Path | None = None,
        write_origin_filter: str | None = None,
        limit: int | None = None,
    ) -> list[Snapshot]:
        """Walk the date tree, load sidecars, apply filters, return
        newest-first."""
        all_snaps: list[Snapshot] = []
        if not self.root.exists():
            return []
        for sidecar in self.root.rglob("*.json"):
            snap = self._load_sidecar(sidecar)
            if snap is None:
                continue
            if write_origin_filter and snap.write_origin != write_origin_filter:
                continue
            if path_filter is not None:
                target = Path(path_filter).resolve()
                if not any(_path_covers(p, target) for p in snap.paths):
                    continue
            all_snaps.append(snap)
        all_snaps.sort(key=lambda s: s.created_at, reverse=True)
        if limit is not None:
            all_snaps = all_snaps[:limit]
        return all_snaps

    def find_most_recent_for(self, path: Path) -> Snapshot | None:
        target = Path(path).resolve()
        for snap in self.list_snapshots():
            if any(_path_covers(p, target) for p in snap.paths):
                return snap
        return None

    # ---- pin / unpin ---------------------------------------------

    def pin(self, snapshot_id: str) -> bool:
        return self._set_pinned(snapshot_id, True)

    def unpin(self, snapshot_id: str) -> bool:
        return self._set_pinned(snapshot_id, False)

    def _set_pinned(self, snapshot_id: str, pinned: bool) -> bool:
        for sidecar in self.root.rglob(f"{snapshot_id}.json"):
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            payload["pinned"] = pinned
            sidecar.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
            return True
        return False

    # ---- restore -------------------------------------------------

    def restore(
        self,
        snapshot: Snapshot,
        *,
        path_filter: Path | None = None,
        confirm: Callable[[str], bool] | None = None,
        dest_root: Path | None = None,
    ) -> list[Path]:
        """Extract ``snapshot`` over the live filesystem.

        ``path_filter``: restrict to members under this path (matched
        against the tar's arcnames relative to :attr:`relative_to`).
        ``confirm``: callback shown a human-readable summary of what
        will be restored; if it returns False, restore aborts and
        returns an empty list.
        ``dest_root``: override the destination (default
        :attr:`relative_to`). Used by tests to extract somewhere
        scratch.

        Returns the list of paths actually restored.
        """
        if not snapshot.tarball_path.exists():
            raise SnapshotError(
                f"tarball missing for snapshot {snapshot.snapshot_id}: {snapshot.tarball_path}"
            )
        target_root = (dest_root or self.relative_to).resolve()

        # Stage 1: enumerate what would be restored.
        with tarfile.open(snapshot.tarball_path, mode="r:gz") as tf:
            members = list(tf.getmembers())
        relevant: list[tarfile.TarInfo] = []
        filter_str: str | None = None
        if path_filter is not None:
            try:
                rel = Path(path_filter).resolve().relative_to(self.relative_to)
                filter_str = rel.as_posix()
            except ValueError:
                # path_filter isn't inside relative_to — nothing matches.
                return []
        for m in members:
            if filter_str is not None:
                if not (m.name == filter_str or m.name.startswith(filter_str + "/")):
                    continue
            relevant.append(m)

        if not relevant:
            return []

        if confirm is not None:
            summary = "\n".join(f"  {m.name}{'/' if m.isdir() else ''}" for m in relevant)
            ok = confirm(f"restore {len(relevant)} entry/entries to {target_root}:\n{summary}")
            if not ok:
                return []

        # Stage 2: extract. We use members=relevant so the tar lib
        # respects the filter. Reject any member whose resolved path
        # would land outside target_root — defends against tar-slip
        # in tarballs that were tampered with on disk (the snapshot
        # dir is local, but other tools or a cloud-sync could mutate
        # it). Also pass filter="data" (Python 3.12+) for the
        # standard hardening; we keep the manual check so the guard
        # works on 3.10/3.11 too.
        target_root_resolved = target_root.resolve()
        safe_members: list[tarfile.TarInfo] = []
        for m in relevant:
            try:
                dest = (target_root / m.name).resolve()
            except (OSError, ValueError):
                continue
            if dest != target_root_resolved and target_root_resolved not in dest.parents:
                continue
            if m.issym() or m.islnk():
                link_target = (dest.parent / m.linkname).resolve()
                if (
                    link_target != target_root_resolved
                    and target_root_resolved not in link_target.parents
                ):
                    continue
            safe_members.append(m)

        restored: list[Path] = []
        with tarfile.open(snapshot.tarball_path, mode="r:gz") as tf:
            extract_kwargs: dict[str, Any] = {
                "path": str(target_root),
                "members": safe_members,
            }
            # Python 3.12+ supports an extraction filter argument.
            if hasattr(tarfile, "data_filter"):
                extract_kwargs["filter"] = "data"
            tf.extractall(**extract_kwargs)
            for m in safe_members:
                if m.isreg() or m.issym():
                    restored.append(target_root / m.name)
        return restored

    # ---- pruning --------------------------------------------------

    def prune(self) -> dict[str, int]:
        """Apply retention policy (age + count + size) — whichever
        fires first. Pinned snapshots bypass every rule."""
        snaps = self.list_snapshots()
        now = dt.datetime.now(dt.timezone.utc)
        removed = 0
        kept = 0
        pinned_count = sum(1 for s in snaps if s.pinned)

        # Build a removable list: not pinned + age-eligible.
        cutoff_age = dt.timedelta(days=self.retention_days)
        removable: list[Snapshot] = []
        for snap in snaps:
            if snap.pinned:
                continue
            if (now - snap.created_at) > cutoff_age:
                removable.append(snap)

        # Also prune if over count: drop oldest unpinned until at or
        # below retention_count.
        non_pinned = [s for s in snaps if not s.pinned]
        if len(non_pinned) > self.retention_count:
            overflow = non_pinned[self.retention_count :]
            for s in overflow:
                if s not in removable:
                    removable.append(s)

        # Size pass: if total bytes still > retention_bytes after the
        # above, keep dropping the oldest unpinned.
        total_bytes = sum(self._tarball_bytes(s) for s in snaps)
        if total_bytes > self.retention_bytes:
            # Drop oldest unpinned until under budget.
            ordered = sorted(
                (s for s in snaps if not s.pinned),
                key=lambda s: s.created_at,
            )
            for s in ordered:
                if total_bytes <= self.retention_bytes:
                    break
                if s in removable:
                    continue
                removable.append(s)
                total_bytes -= self._tarball_bytes(s)

        for snap in removable:
            self._remove_snapshot(snap)
            removed += 1
        kept = len(snaps) - removed
        return {"removed": removed, "kept": kept, "pinned": pinned_count}

    def _tarball_bytes(self, snap: Snapshot) -> int:
        try:
            return snap.tarball_path.stat().st_size
        except OSError:
            return 0

    def _remove_snapshot(self, snap: Snapshot) -> None:
        for p in (snap.tarball_path, snap.sidecar_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                logger.debug("snapshot unlink failed: %s", p, exc_info=True)


# ---- helpers --------------------------------------------------------


def _path_covers(snapshot_path: Path, target: Path) -> bool:
    """True if ``snapshot_path`` is ``target`` or an ancestor.

    Used by find_most_recent_for / list_snapshots --path-filter: a
    snapshot whose ``paths`` includes the user's whole skill dir
    "covers" any individual file under that dir.
    """
    snapshot_path = Path(snapshot_path)
    target = Path(target)
    try:
        target.relative_to(snapshot_path)
        return True
    except ValueError:
        return snapshot_path == target
