"""Persistent task tracker tools (T6-06.2 — refactored from in-memory dict).

External API and behaviour the agent sees is **byte-identical**
to the previous in-memory implementation:

  TaskCreate(subject, description, activeForm) → str
  TaskUpdate(taskId, status?, subject?, description?, activeForm?) → str
  TaskList() → str

Status values exposed externally still come from the
Claude-Code-style vocabulary:

  pending | in_progress | completed | deleted

Internally everything lives in :class:`athena.tasks.model.TaskStore`
with the canonical kanban vocabulary:

  todo | doing | done | blocked

The mapping at the boundary is the only change. The store also
gains persistence + workspace-scoping + goal-subgoal projection
"for free" — T6-06.4 wires the goal projection.

A short reminder: the task tools are workspace + session-scoped
in the store; this module's helpers carry workspace into create
so the board for project A doesn't show project B's cards.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from .. import ui
from .registry import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool-facing vocabulary (Claude Code style) ↔ internal kanban vocabulary
# ---------------------------------------------------------------------------


Status = Literal["pending", "in_progress", "completed", "deleted"]


_EXT_TO_INT: dict[str, str] = {
    "pending": "todo",
    "in_progress": "doing",
    "completed": "done",
}

_INT_TO_EXT: dict[str, str] = {v: k for k, v in _EXT_TO_INT.items()}
# blocked has no external equivalent — surfaced as "in_progress"
# in the tool output for back-compat (the agent already
# understands "in_progress" as the active state).
_INT_TO_EXT["blocked"] = "in_progress"


# ---------------------------------------------------------------------------
# Module-level store (lazy)
# ---------------------------------------------------------------------------


_store: Any = None


def _resolve_store() -> Any:
    """Lazy-build the TaskStore once per process. The store
    survives across run_turn calls; it's the SAME store the
    board reads from (T6-06.3) and the goal projection writes
    to (T6-06.4)."""
    global _store
    if _store is not None:
        return _store
    from ..config import load_config, profile_dir
    from ..tasks.model import TaskStore, default_task_store_path

    cfg = load_config()
    profile = getattr(cfg, "profile", None) or "default"
    path = default_task_store_path(cfg, profile_dir(profile))
    _store = TaskStore(path=path)
    return _store


def _resolve_workspace() -> str:
    """Get the active workspace path. Resolved from file_ops's
    workspace at call time so a /cwd change is picked up."""
    try:
        from . import file_ops

        return str(file_ops._WORKSPACE)  # noqa: SLF001 — fine for tools
    except Exception:  # noqa: BLE001
        return ""


def _reset_for_tests() -> None:
    """Test affordance — clear the cached store so a fresh
    cfg / path is honoured per test."""
    global _store
    _store = None


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


def _ext_status(internal: str) -> str:
    return _INT_TO_EXT.get(internal, "pending")


def _int_status(external: str) -> str | None:
    """Map external → internal. ``"deleted"`` returns None
    (delete-is-special, handled by the caller)."""
    if external == "deleted":
        return None
    return _EXT_TO_INT.get(external)


# ---------------------------------------------------------------------------
# Note ↔ (description, activeForm) round-trip
# ---------------------------------------------------------------------------


def _encode_note(description: str, activeForm: str, *, subject: str) -> str | None:
    parts: list[str] = []
    if description and description != subject:
        parts.append(description)
    if activeForm:
        parts.append(f"activeForm: {activeForm}")
    return "\n".join(parts) if parts else None


def _existing_description(note: str | None) -> str:
    if not note:
        return ""
    lines = note.splitlines()
    desc_lines: list[str] = []
    for line in lines:
        if line.startswith("activeForm: "):
            break
        desc_lines.append(line)
    return "\n".join(desc_lines).strip()


def _existing_active_form(note: str | None) -> str:
    if not note:
        return ""
    for line in note.splitlines():
        if line.startswith("activeForm: "):
            return line[len("activeForm: "):].strip()
    return ""


# ---------------------------------------------------------------------------
# Tools — API surface is identical to the pre-T6-06.2 version
# ---------------------------------------------------------------------------


@tool(
    name="TaskCreate",
    toolset="core",
    description=(
        "Use this tool to track multi-step work. Create a task with a clear, "
        "actionable subject (imperative form) and a short description. "
        "Tasks start as 'pending'; mark them 'in_progress' when you start "
        "and 'completed' as soon as the work is done — don't batch. "
        "Tasks persist across restart (T6-06) and show up on the board "
        "(`athena board`)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Brief actionable title."},
            "description": {"type": "string", "description": "What needs to be done."},
            "activeForm": {
                "type": "string",
                "description": "Optional present-continuous form for the spinner.",
            },
        },
        "required": ["subject", "description"],
    },
)
def TaskCreate(subject: str, description: str, activeForm: str = "") -> str:
    store = _resolve_store()
    workspace = _resolve_workspace()
    note = _encode_note(description, activeForm, subject=subject)
    task = store.create(
        title=subject,
        status="todo",
        workspace=workspace or None,
        note=note,
    )
    ui.info(f"task {task.id} created: {subject}")
    return f"Task {task.id} created: {subject}"


@tool(
    name="TaskUpdate",
    toolset="core",
    description=(
        "Update a task's status, subject, or description. Set status to "
        "'in_progress' when you start work, 'completed' when done. Only "
        "mark a task completed when you've FULLY accomplished it — if you "
        "hit a blocker, leave it 'in_progress' and create a new task for "
        "what's blocking. Use 'deleted' to remove a stale task."
    ),
    parameters={
        "type": "object",
        "properties": {
            "taskId": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "deleted"],
            },
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "activeForm": {"type": "string"},
        },
        "required": ["taskId"],
    },
)
def TaskUpdate(
    taskId: str,
    status: str | None = None,
    subject: str | None = None,
    description: str | None = None,
    activeForm: str | None = None,
) -> str:
    store = _resolve_store()
    existing = store.get(taskId)
    if existing is None:
        return f"ERROR: no task {taskId}"

    if status == "deleted":
        store.delete(taskId)
        ui.info(f"task {taskId} deleted")
        return f"Task {taskId} deleted"

    update_kwargs: dict[str, Any] = {}
    if status is not None:
        internal = _int_status(status)
        if internal is None:
            return f"ERROR: invalid status {status!r}"
        update_kwargs["status"] = internal

    if subject is not None:
        update_kwargs["title"] = subject

    if description is not None or activeForm is not None:
        # Replace the note with a fresh encode using the new
        # description / activeForm (falling back to existing
        # values for the field that wasn't passed). This matches
        # the pre-T6-06.2 contract where TaskUpdate(description=X)
        # sets description to X.
        new_desc = (
            description
            if description is not None
            else _existing_description(existing.note)
        )
        new_active = (
            activeForm
            if activeForm is not None
            else _existing_active_form(existing.note)
        )
        update_kwargs["note"] = _encode_note(
            new_desc, new_active, subject=subject or existing.title
        ) or ""

    if not update_kwargs:
        return f"Task {taskId}: no changes"

    try:
        updated = store.update(taskId, **update_kwargs)
    except (ValueError, KeyError) as e:
        return f"ERROR: {e}"

    ext = _ext_status(updated.status)
    ui.info(f"task {taskId} -> {ext}: {updated.title}")
    return f"Task {taskId} updated: status={ext}"


@tool(
    name="TaskList",
    toolset="core",
    description=(
        "List all current tasks with their status. Use this to see what's "
        "pending, what's in progress, and what's been completed. The same "
        "tasks show on the kanban board (`athena board`)."
    ),
    parameters={"type": "object", "properties": {}},
)
def TaskList() -> str:
    store = _resolve_store()
    workspace = _resolve_workspace()
    tasks = store.list(workspace=workspace or None)
    if not tasks:
        return "(no tasks)"
    lines: list[str] = []
    for t in tasks:
        ext = _ext_status(t.status)
        marker = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "completed": "[x]",
        }.get(ext, "[?]")
        lines.append(f"  {t.id} {marker} {t.title}")
        desc = _existing_description(t.note)
        if desc and desc != t.title:
            lines.append(f"        {desc}")
    return "\n".join(lines)
