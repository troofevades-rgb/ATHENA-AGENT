"""Conversation-level checkpoint and rollback (T3-03).

A *checkpoint* captures four pieces of state for the current session:

1. ``session_message_count`` — the line offset in the session's
   JSONL log. Rollback truncates the log to this position.
2. ``file_snapshot_id`` — a content-addressed snapshot of any
   files the agent modified between the previous checkpoint and
   this one (tracked via :func:`track_modified_file` from
   ``athena.tools.file_ops`` / ``patch_apply``).
3. ``skill_state_token`` — a manifest hash + saved-content blob
   capturing the skill catalogue. Restore re-writes any skill
   file whose current content differs from the captured copy.
4. ``memory_state_token`` — same shape for the active profile's
   memory directory.

Rollback is itself undoable: before reverting, the current state
is auto-checkpointed as ``pre-rollback-of-<id>`` so the user can
``/rollback-to`` that to get back to where they were.

A :class:`contextvars.ContextVar` holds the active manager for the
current Agent so file-write tools can post modifications to it
without an explicit argument plumbing. The Agent sets it once at
session start; file_ops consults it on every write.

Snapshots aren't routed through ``athena.safety.secure_files``
because checkpoints aren't credential material; they live under
``~/.athena/profiles/<profile>/checkpoints/<session_id>/`` at
default permissions. The session JSONL itself stays at its
existing location and permissions.
"""

from __future__ import annotations

import contextvars
import dataclasses
import datetime
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CheckpointNotFound(LookupError):
    """Raised when ``rollback_to`` can't find the requested checkpoint."""


class InFlightToolCallError(RuntimeError):
    """Rollback attempted while a tool call is mid-flight."""


# ---------------------------------------------------------------------------
# Active-manager ContextVar
# ---------------------------------------------------------------------------


_active_manager: contextvars.ContextVar[CheckpointManager | None] = contextvars.ContextVar(
    "athena_checkpoint_manager", default=None
)


def get_active_checkpoint_manager() -> CheckpointManager | None:
    """Return the :class:`CheckpointManager` for the current Agent, or
    ``None`` if no checkpoint manager is active. file_ops calls this
    on every write to record modifications."""
    return _active_manager.get()


def set_active_checkpoint_manager(mgr: CheckpointManager | None) -> None:
    _active_manager.set(mgr)


def track_modified_file(path: Path | str) -> None:
    """Convenience: notify the active CheckpointManager (if any) that
    ``path`` was modified in the current turn. Safe no-op when no
    manager is registered — keeps file_ops simple."""
    mgr = _active_manager.get()
    if mgr is None:
        return
    try:
        mgr.track_modified_file(Path(path))
    except Exception:  # noqa: BLE001
        # Tracking is best-effort. A buggy manager must never block
        # a write.
        logger.debug("track_modified_file failed for %s", path, exc_info=True)


# ---------------------------------------------------------------------------
# Skill / memory state snapshotting (inline — no class hierarchy)
# ---------------------------------------------------------------------------


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _walk_dir(root: Path, *, patterns: tuple[str, ...] = ("*.md",)) -> list[Path]:
    """Return every file under ``root`` matching one of ``patterns``,
    sorted for stable manifest hashing. Symlinks not followed."""
    if not root.exists():
        return []
    out: list[Path] = []
    for pattern in patterns:
        out.extend(p for p in root.rglob(pattern) if p.is_file())
    return sorted(set(out))


def snapshot_skills(workspace: Path | None, snapshot_dir: Path) -> str:
    """Capture every ``*.md`` under the user + workspace skill search
    paths. Returns an opaque token (manifest hash) and stashes the
    full manifest under ``snapshot_dir/skills/<token>/``.

    Manifest layout:

        snapshot_dir/skills/<token>/manifest.json   -- {paths: [{rel, sha, base_role}], ...}
        snapshot_dir/skills/<token>/files/<sha>     -- captured file bytes (content-addressed)
    """
    from ..skills.discovery import search_paths

    bases: list[tuple[str, Path]] = []
    # search_paths returns user-level first, then workspace.
    for i, base in enumerate(search_paths(workspace)):
        if not base.exists():
            continue
        bases.append((f"base{i}", base))

    entries: list[dict[str, str]] = []
    files_to_capture: dict[str, bytes] = {}
    for base_role, base in bases:
        for p in _walk_dir(base):
            try:
                data = p.read_bytes()
            except OSError:
                continue
            sha = hashlib.sha256(data).hexdigest()
            entries.append(
                {
                    "rel": p.relative_to(base).as_posix(),
                    "base": str(base),
                    "base_role": base_role,
                    "sha": sha,
                }
            )
            files_to_capture[sha] = data

    return _persist_state_snapshot(
        snapshot_dir / "skills",
        manifest={"kind": "skills", "entries": entries},
        files=files_to_capture,
    )


def snapshot_memory(profile_dir: Path, snapshot_dir: Path) -> str:
    """Capture every ``*.md`` under ``<profile_dir>/memory/``."""
    memory_dir = profile_dir / "memory"
    entries: list[dict[str, str]] = []
    files_to_capture: dict[str, bytes] = {}
    for p in _walk_dir(memory_dir):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        sha = hashlib.sha256(data).hexdigest()
        entries.append(
            {
                "rel": p.relative_to(memory_dir).as_posix(),
                "base": str(memory_dir),
                "sha": sha,
            }
        )
        files_to_capture[sha] = data
    return _persist_state_snapshot(
        snapshot_dir / "memory",
        manifest={"kind": "memory", "entries": entries},
        files=files_to_capture,
    )


def _persist_state_snapshot(
    root: Path, *, manifest: dict[str, Any], files: dict[str, bytes]
) -> str:
    """Write manifest + captured files; return the manifest hash as
    the token. Idempotent: same content → same token → same dir."""
    blob = json.dumps(manifest, sort_keys=True).encode("utf-8")
    token = hashlib.sha256(blob).hexdigest()[:24]
    target = root / token
    if (target / "manifest.json").exists():
        return token
    (target / "files").mkdir(parents=True, exist_ok=True)
    for sha, data in files.items():
        out = target / "files" / sha
        if not out.exists():
            out.write_bytes(data)
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return token


def restore_skills(token: str, snapshot_dir: Path) -> int:
    """Re-write any skill file whose current content differs from the
    captured copy. Returns the number of files restored."""
    return _restore_state_snapshot(snapshot_dir / "skills" / token)


def restore_memory(token: str, snapshot_dir: Path) -> int:
    return _restore_state_snapshot(snapshot_dir / "memory" / token)


def _restore_state_snapshot(target: Path) -> int:
    manifest_path = target / "manifest.json"
    if not manifest_path.exists():
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored = 0
    for entry in manifest.get("entries", []):
        base = Path(entry["base"])
        rel = entry["rel"]
        sha = entry["sha"]
        dest = base / rel
        blob = target / "files" / sha
        if not blob.exists():
            logger.warning("restore_state: captured blob %s missing for %s", sha, dest)
            continue
        captured = blob.read_bytes()
        try:
            current = dest.read_bytes() if dest.exists() else b""
        except OSError:
            current = b""
        if current == captured:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(captured)
        restored += 1
    return restored


# ---------------------------------------------------------------------------
# Audit event log
# ---------------------------------------------------------------------------


class CheckpointAuditLog:
    """Tiny JSONL appender separate from MutationAuditLog.

    Lives at ``<checkpoint_dir>/audit.jsonl``. Each line:
    ``{ts, event_type, summary, data}``. T3-04's diff tools can
    surface entries from here.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, event_type: str, summary: str, data: dict[str, Any]) -> None:
        entry = {
            "ts": _now_iso(),
            "event_type": event_type,
            "summary": summary,
            "data": data,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")

    def query(
        self,
        *,
        event_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and entry.get("event_type") != event_type:
                continue
            ts = entry.get("ts", "")
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        return out


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Checkpoint dataclass + manager
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Checkpoint:
    id: str
    label: str
    session_id: str
    created_at: str
    session_message_count: int
    file_snapshot_id: str | None
    skill_state_token: str
    memory_state_token: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        return cls(**d)


# Type alias for the file conflict callback.
ConflictResolver = Callable[[Path, bytes, bytes], str]


class CheckpointManager:
    """One per Agent session.

    Construction is decoupled from the Agent for testability: pass
    in a snapshot store, an optional profile dir, and the session
    JSONL path. Tests inject a tmp_path tree; the Agent wires this
    up using the real paths in ``Agent.__init__``.
    """

    def __init__(
        self,
        *,
        session_id: str,
        session_log_path: Path,
        checkpoint_dir: Path,
        snapshot_store: Any,
        profile_dir: Path,
        workspace: Path | None = None,
        state_snapshot_dir: Path | None = None,
        audit_log: CheckpointAuditLog | None = None,
    ):
        self.session_id = session_id
        self.session_log_path = Path(session_log_path)
        self.checkpoint_dir = Path(checkpoint_dir).expanduser()
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_store = snapshot_store
        self.profile_dir = Path(profile_dir)
        self.workspace = Path(workspace) if workspace is not None else None
        self.state_snapshot_dir = (
            Path(state_snapshot_dir)
            if state_snapshot_dir is not None
            else self.checkpoint_dir / "state"
        )
        self.state_snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log = audit_log or CheckpointAuditLog(self.checkpoint_dir / "audit.jsonl")

        self._tracked_modified_files: set[Path] = set()
        self._tool_call_in_flight: bool = False

    # ------------------------------------------------------------------
    # Modification tracking
    # ------------------------------------------------------------------

    def track_modified_file(self, path: Path) -> None:
        """Called by file_ops whenever a file is written. Idempotent."""
        try:
            resolved = Path(path).resolve()
        except OSError:
            resolved = Path(path)
        self._tracked_modified_files.add(resolved)

    def reset_modification_tracking(self) -> None:
        self._tracked_modified_files.clear()

    # ------------------------------------------------------------------
    # In-flight tool-call hint (set by Agent around tool dispatch)
    # ------------------------------------------------------------------

    def set_tool_call_in_flight(self, in_flight: bool) -> None:
        self._tool_call_in_flight = bool(in_flight)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, *, label: str | None = None, notes: str = "") -> Checkpoint:
        cid = f"cp-{uuid.uuid4().hex[:12]}"
        if label is None:
            label = f"checkpoint-{cid}"

        # Snapshot modified files via the existing SnapshotStore.
        file_snapshot_id: str | None = None
        if self._tracked_modified_files:
            existing = [p for p in self._tracked_modified_files if p.exists()]
            if existing:
                snap = self.snapshot_store._create_snapshot(
                    tuple(existing),
                    session_id=self.session_id,
                    tool_name=f"checkpoint:{label}",
                    tool_call_id=cid,
                    parent_session_id=None,
                )
                file_snapshot_id = snap.snapshot_id

        # State tokens
        skill_token = snapshot_skills(self.workspace, self.state_snapshot_dir)
        memory_token = snapshot_memory(self.profile_dir, self.state_snapshot_dir)

        # Session log line count BEFORE the synthetic marker.
        session_message_count = self._count_session_messages()

        cp = Checkpoint(
            id=cid,
            label=label,
            session_id=self.session_id,
            created_at=_now_iso(),
            session_message_count=session_message_count,
            file_snapshot_id=file_snapshot_id,
            skill_state_token=skill_token,
            memory_state_token=memory_token,
            notes=notes,
        )
        self._persist(cp)
        self.reset_modification_tracking()

        self.audit_log.record(
            event_type="checkpoint",
            summary=f"Checkpoint {label!r} created (id={cid})",
            data=cp.to_dict(),
        )
        logger.info(
            "Created checkpoint %s (label=%r) for session %s",
            cid,
            label,
            self.session_id,
        )
        return cp

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback_to(
        self,
        label_or_id: str,
        *,
        on_file_conflict: ConflictResolver | None = None,
    ) -> Checkpoint:
        if self._tool_call_in_flight:
            raise InFlightToolCallError(
                "Cannot rollback while a tool call is in flight. Cancel the current turn first."
            )
        cp = self._find(label_or_id)
        if cp is None:
            raise CheckpointNotFound(f"No checkpoint matching {label_or_id!r}")

        # Save current state first so the rollback itself is undoable.
        pre_rollback = self.create(
            label=f"pre-rollback-of-{cp.id}",
            notes=f"Auto-created before rollback to {cp.label!r}",
        )

        # 1. Truncate session log to the captured offset.
        self._truncate_session_log(cp.session_message_count)

        # 2. Restore files from the captured snapshot.
        if cp.file_snapshot_id is not None:
            self._restore_file_snapshot(cp.file_snapshot_id, on_file_conflict)

        # 3. Skill and memory state restoration.
        restored_skills = restore_skills(cp.skill_state_token, self.state_snapshot_dir)
        restored_memory = restore_memory(cp.memory_state_token, self.state_snapshot_dir)

        # 4. Append the synthetic system marker.
        self._append_rollback_marker(cp)

        self.audit_log.record(
            event_type="rollback",
            summary=f"Rolled back to checkpoint {cp.label!r} (id={cp.id})",
            data={
                "rolled_back_to": cp.id,
                "pre_rollback_checkpoint": pre_rollback.id,
                "skills_restored": restored_skills,
                "memory_restored": restored_memory,
            },
        )
        logger.info(
            "Rolled back session %s to checkpoint %s (label=%r); pre-rollback state captured as %s",
            self.session_id,
            cp.id,
            cp.label,
            pre_rollback.id,
        )
        return cp

    # ------------------------------------------------------------------
    # List / find / purge
    # ------------------------------------------------------------------

    def list(self) -> list[Checkpoint]:
        out: list[Checkpoint] = []
        for path in sorted(self.checkpoint_dir.glob("cp-*.json")):
            try:
                out.append(Checkpoint.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError) as e:
                logger.warning("Skipping malformed checkpoint %s: %s", path, e)
        out.sort(key=lambda c: c.created_at)
        return out

    def _find(self, label_or_id: str) -> Checkpoint | None:
        for cp in self.list():
            if cp.id == label_or_id or cp.label == label_or_id:
                return cp
        return None

    def purge_pre_rollback(self) -> int:
        removed = 0
        for cp in self.list():
            if cp.label.startswith("pre-rollback-"):
                (self.checkpoint_dir / f"{cp.id}.json").unlink(missing_ok=True)
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _persist(self, cp: Checkpoint) -> None:
        from ..safety.secure_files import secure_write_json

        # Mode 0o644 — checkpoint data is not credential material; using
        # secure_write_json for the atomic-replace semantics, not for the
        # restrictive mode.
        secure_write_json(
            self.checkpoint_dir / f"{cp.id}.json",
            cp.to_dict(),
            mode=0o644,
        )

    def _count_session_messages(self) -> int:
        if not self.session_log_path.exists():
            return 0
        return sum(
            1
            for line in self.session_log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def _truncate_session_log(self, target_count: int) -> None:
        if not self.session_log_path.exists():
            return
        lines = self.session_log_path.read_text(encoding="utf-8").splitlines()
        # Keep only the first `target_count` non-blank lines.
        kept: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            if len(kept) >= target_count:
                break
            kept.append(line)
        from ..safety.secure_files import secure_write_text

        secure_write_text(
            self.session_log_path,
            "\n".join(kept) + ("\n" if kept else ""),
            mode=0o644,
        )

    def _append_rollback_marker(self, cp: Checkpoint) -> None:
        marker = {
            "role": "system",
            "content": (
                f"[Session rolled back to checkpoint {cp.label!r} "
                f"(id={cp.id}) at {_now_iso()}. The intervening turns "
                f"and any file/skill/memory mutations have been reverted.]"
            ),
        }
        with open(self.session_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(marker, separators=(",", ":")) + "\n")

    def _restore_file_snapshot(
        self,
        snapshot_id: str,
        on_file_conflict: ConflictResolver | None,
    ) -> None:
        """Find the Snapshot record matching ``snapshot_id`` and call
        ``SnapshotStore.restore``.

        ``on_file_conflict`` is a callback ``(path, original_bytes,
        current_bytes) -> "overwrite" | "skip" | "diff"``. Wired into
        SnapshotStore's ``confirm`` parameter — a "skip" return aborts
        the whole restore (the existing SnapshotStore restore is
        all-or-nothing).
        """
        sidecars = list(self.snapshot_store.root.rglob(f"{snapshot_id}.json"))
        if not sidecars:
            logger.warning("snapshot %s missing during rollback", snapshot_id)
            return
        snap = self.snapshot_store._load_sidecar(sidecars[0])
        if snap is None:
            logger.warning("snapshot sidecar %s unreadable", sidecars[0])
            return

        confirm: Callable[[str], bool] | None = None
        if on_file_conflict is not None:

            def _confirm(_summary: str) -> bool:
                # Tunnel SnapshotStore's text-summary confirm into our
                # per-file ConflictResolver: ask the user once whether
                # to overwrite the entire set. The richer per-file
                # conflict path is a future enhancement; SnapshotStore's
                # current API doesn't expose pre-extract diffs.
                first_path = snap.paths[0] if snap.paths else Path("?")
                action = on_file_conflict(first_path, b"", b"")
                return action == "overwrite"

            confirm = _confirm

        self.snapshot_store.restore(snap, confirm=confirm)
