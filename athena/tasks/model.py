"""Persisted task model (T6-06.1).

A JSON-backed task store. One model serves both the existing
``TaskCreate``/``TaskUpdate``/``TaskList`` tool surface AND the
goal-loop subgoals — the design's single-store invariant.

  Status: "todo" | "doing" | "done" | "blocked"

The existing ``athena/tools/task.py`` uses a different vocabulary
(``pending`` / ``in_progress`` / ``completed``). T6-06.2 will
keep that external surface stable while mapping to the canonical
status names internally — the agent doesn't see a status rename.

Why JSON not SQLite: athena's per-user scale (tens to hundreds
of tasks per workspace) fits comfortably in a flat file. JSON
keeps the store inspectable / editable by humans, which matches
the rest of athena's persistence layer (skills, memory, audit
logs, vectors).

Persistence layout:

  ``<task_store_path>``  one JSON file per profile, default
                         ``<profile_dir>/tasks/tasks.json``.
                         Atomic-replace writes via
                         :func:`athena.safety.secure_files.secure_write_json`
                         (the same atomic-replace + fsync that
                         every other operational file uses).

Concurrency: the store uses a process-local lock on every
mutate. Athena's agent is single-threaded for tool calls, so
contention is rare; the lock is belt-and-braces for fork-like
contexts and the future board TUI's refresh thread.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical status vocabulary
# ---------------------------------------------------------------------------


Status = Literal["todo", "doing", "done", "blocked"]
_STATUS_VALUES: frozenset[str] = frozenset(("todo", "doing", "done", "blocked"))


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Task:
    """One task / subgoal card.

    ``goal_id`` distinguishes a regular task (None) from a card
    that's projected from a T5-07 goal's subgoal (set to the
    goal's id). Both shapes live in the same store; filters
    select per-call.

    ``workspace`` is the workspace path this task belongs to —
    the board is workspace-scoped by default so cards from
    other projects don't pollute the view.

    ``order`` is an explicit per-column ordering used by the
    board to keep cards stable across reloads + to support
    drag-equivalent re-ordering later. Auto-assigned at
    create time; mutated by ``update(..., order=)``.

    ``note`` carries the original tool-call description / any
    free-form annotation — the title is the card label, the
    note is the detail.
    """

    id: str
    title: str
    status: Status = "todo"
    order: int = 0
    parent_id: str | None = None
    goal_id: str | None = None
    session_id: str | None = None
    workspace: str | None = None
    note: str | None = None
    created_at: float = dataclasses.field(default_factory=time.time)
    updated_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Task:
        status = d.get("status", "todo")
        if status not in _STATUS_VALUES:
            logger.debug("unknown status %r in stored task, normalising", status)
            status = "todo"
        return cls(
            id=str(d["id"]),
            title=str(d.get("title", "")),
            status=status,
            order=int(d.get("order", 0)),
            parent_id=d.get("parent_id") or None,
            goal_id=d.get("goal_id") or None,
            session_id=d.get("session_id") or None,
            workspace=d.get("workspace") or None,
            note=d.get("note") or None,
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


_TASKS_FILENAME = "tasks.json"


class TaskStore:
    """Persistent JSON-backed task store.

    Surface:

      ``create(title, *, status, goal_id, parent_id, session_id,
               workspace, note)``  → Task
      ``get(task_id)``              → Task | None
      ``update(task_id, *, status, title, order, note, ...)``
                                    → Task
      ``delete(task_id)``           → bool
      ``list(*, workspace, goal_id, status, include_archived)``
                                    → list[Task]
      ``archive_done(older_than_days)``
                                    → int (count archived)
      ``clear()``                   → int (count removed)
    """

    def __init__(self, *, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, Task] = self._load()
        self._archived: list[Task] = []  # in-memory archive for
        # archive_done()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        status: Status = "todo",
        goal_id: str | None = None,
        parent_id: str | None = None,
        session_id: str | None = None,
        workspace: str | None = None,
        note: str | None = None,
    ) -> Task:
        """Create a task at the end of its column's order."""
        if not title or not str(title).strip():
            raise ValueError("title required")
        if status not in _STATUS_VALUES:
            raise ValueError(f"invalid status: {status!r}")
        with self._lock:
            order = self._next_order_for(status, workspace=workspace, goal_id=goal_id)
            task = Task(
                id=_new_id(),
                title=str(title).strip(),
                status=status,
                order=order,
                parent_id=parent_id,
                goal_id=goal_id,
                session_id=session_id,
                workspace=workspace,
                note=note,
            )
            self._tasks[task.id] = task
            self._save()
        return task

    def update(
        self,
        task_id: str,
        *,
        status: Status | None = None,
        title: str | None = None,
        order: int | None = None,
        note: str | None = None,
        parent_id: str | None = None,
        goal_id: str | None = None,
    ) -> Task:
        """Mutate the named task. Raises ``KeyError`` if it
        doesn't exist — the caller (tool path) maps to a
        structured error."""
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                raise KeyError(f"no task with id {task_id!r}")
            if status is not None:
                if status not in _STATUS_VALUES:
                    raise ValueError(f"invalid status: {status!r}")
                if status != t.status:
                    # Re-order: the task moves to the END of its
                    # new column. Compute the new order BEFORE
                    # writing the new status so the lookup
                    # doesn't count this task itself in its new
                    # column.
                    new_order = self._next_order_for(
                        status,
                        workspace=t.workspace,
                        goal_id=t.goal_id,
                    )
                    t.status = status
                    t.order = new_order
            if title is not None:
                t.title = str(title).strip()
            if order is not None:
                t.order = int(order)
            if note is not None:
                t.note = note
            if parent_id is not None:
                t.parent_id = parent_id or None
            if goal_id is not None:
                t.goal_id = goal_id or None
            t.updated_at = time.time()
            self._save()
            return t

    def delete(self, task_id: str) -> bool:
        with self._lock:
            existed = task_id in self._tasks
            self._tasks.pop(task_id, None)
            if existed:
                self._save()
            return existed

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(
        self,
        *,
        workspace: str | None = None,
        goal_id: str | None = None,
        status: Status | None = None,
        include_archived: bool = False,
    ) -> list[Task]:
        """Filtered listing.

        ``workspace=None`` matches every workspace; pass an
        explicit empty-string-or-real value to filter.
        ``goal_id`` has the same semantics. ``status`` filters
        on the canonical status.

        Returned list is sorted by (status, order) so the board
        can render columns directly.
        """
        with self._lock:
            out: list[Task] = []
            for t in self._tasks.values():
                if workspace is not None and t.workspace != workspace:
                    continue
                if goal_id is not None and t.goal_id != goal_id:
                    continue
                if status is not None and t.status != status:
                    continue
                out.append(t)
            if include_archived:
                out.extend(
                    t
                    for t in self._archived
                    if (workspace is None or t.workspace == workspace)
                    and (goal_id is None or t.goal_id == goal_id)
                    and (status is None or t.status == status)
                )
        out.sort(key=lambda t: (_STATUS_ORDER.get(t.status, 99), t.order, t.created_at))
        return out

    def all(self) -> list[Task]:
        """Every live task, no filter — for admin / status."""
        return self.list()

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def archive_done(self, older_than_days: float) -> int:
        """Move ``done`` tasks older than ``older_than_days``
        into the in-memory archive (the live list shrinks).
        Returns the number archived. The archive itself is NOT
        persisted to disk in v1 — done tasks past the threshold
        simply disappear from the board on the next archive
        sweep. The agent's existing memory / audit log is the
        right place for "I finished X last week".

        ``older_than_days <= 0`` is a no-op (used in tests for
        "archive everything" → operate-with-zero would risk
        deleting still-relevant done tasks; require an explicit
        positive threshold).
        """
        if older_than_days <= 0:
            return 0
        cutoff = time.time() - (older_than_days * 86400.0)
        with self._lock:
            to_archive = [
                t for t in self._tasks.values() if t.status == "done" and t.updated_at < cutoff
            ]
            for t in to_archive:
                self._tasks.pop(t.id, None)
                self._archived.append(t)
            if to_archive:
                self._save()
        return len(to_archive)

    def clear(self) -> int:
        """Drop every live task. Returns the count removed.
        Doesn't touch the archive."""
        with self._lock:
            n = len(self._tasks)
            self._tasks.clear()
            if n:
                self._save()
        return n

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Task]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            # Move the unreadable file aside before returning empty
            # so the FIRST subsequent _save() doesn't atomically
            # overwrite the user's task board with an empty list.
            # The .corrupt.<ts> sidecar lets the user recover
            # manually; we log loudly because silent data loss is
            # the failure mode this guard exists to prevent.
            backup = self.path.with_suffix(self.path.suffix + f".corrupt.{int(time.time())}")
            try:
                self.path.rename(backup)
                logger.error(
                    "task store unreadable at %s: %s -- moved aside to %s",
                    self.path,
                    e,
                    backup,
                )
            except OSError:
                logger.error(
                    "task store unreadable at %s: %s (and could not move aside)",
                    self.path,
                    e,
                )
            return {}
        out: dict[str, Task] = {}
        for d in raw if isinstance(raw, list) else []:
            try:
                t = Task.from_dict(d)
                out[t.id] = t
            except (TypeError, KeyError, ValueError) as e:
                logger.debug("skipping malformed task: %s", e)
        return out

    def _save(self) -> None:
        from ..safety.secure_files import secure_write_json

        payload = [t.to_dict() for t in self._tasks.values()]
        # Tasks aren't credential-grade but the atomic-replace
        # semantics of secure_write_json are exactly what we want
        # for a frequently-rewritten store. Mode 0o600 is fine
        # for per-user data.
        secure_write_json(self.path, payload, mode=0o600)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _next_order_for(
        self,
        status: Status,
        *,
        workspace: str | None,
        goal_id: str | None,
    ) -> int:
        """Compute the next order number for a column / scope.

        Caller already holds the lock."""
        max_order = -1
        for t in self._tasks.values():
            if t.status != status:
                continue
            if workspace is not None and t.workspace != workspace:
                continue
            if goal_id is not None and t.goal_id != goal_id:
                continue
            if t.order > max_order:
                max_order = t.order
        return max_order + 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Column display order for the board. Left → right.
_STATUS_ORDER: dict[str, int] = {
    "todo": 0,
    "doing": 1,
    "blocked": 2,
    "done": 3,
}


def _new_id() -> str:
    """Short, sortable-ish IDs. UUID4 first 12 hex chars is
    plenty at per-user scale and reads cleanly in CLI output."""
    return f"t-{uuid.uuid4().hex[:12]}"


def default_task_store_path(cfg: Any, profile_dir: Path) -> Path:
    """Resolve the task-store path: cfg override wins; else
    ``<profile_dir>/tasks/tasks.json``."""
    explicit = getattr(cfg, "task_store_path", None)
    if explicit:
        return Path(str(explicit)).expanduser()
    return Path(profile_dir) / "tasks" / _TASKS_FILENAME
