"""In-memory task tracker tools, mirroring Claude Code's TaskCreate/Update/List.

Tasks live for the lifetime of the agent process. They aren't persisted —
they're a conversation-scoped scratchpad for breaking work into steps. Use
the memory system for cross-session state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from .. import ui
from .registry import tool

Status = Literal["pending", "in_progress", "completed", "deleted"]


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: Status = "pending"
    activeForm: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)


_TASKS: dict[str, Task] = {}
_NEXT_ID = 1


def _next_id() -> str:
    global _NEXT_ID
    n = _NEXT_ID
    _NEXT_ID += 1
    return str(n)


@tool(
    name="TaskCreate",
    toolset="core",
    description=(
        "Use this tool to track multi-step work. Create a task with a clear, "
        "actionable subject (imperative form) and a short description. "
        "Tasks start as 'pending'; mark them 'in_progress' when you start "
        "and 'completed' as soon as the work is done — don't batch."
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
    tid = _next_id()
    _TASKS[tid] = Task(id=tid, subject=subject, description=description, activeForm=activeForm)
    ui.info(f"task #{tid} created: {subject}")
    return f"Task #{tid} created: {subject}"


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
    t = _TASKS.get(taskId)
    if not t:
        return f"ERROR: no task #{taskId}"
    if status:
        if status == "deleted":
            del _TASKS[taskId]
            ui.info(f"task #{taskId} deleted")
            return f"Task #{taskId} deleted"
        if status not in ("pending", "in_progress", "completed"):
            return f"ERROR: invalid status {status!r}"
        t.status = status  # type: ignore[assignment]
    if subject is not None:
        t.subject = subject
    if description is not None:
        t.description = description
    if activeForm is not None:
        t.activeForm = activeForm
    t.updated = time.time()
    ui.info(f"task #{taskId} -> {t.status}: {t.subject}")
    return f"Task #{taskId} updated: status={t.status}"


@tool(
    name="TaskList",
    toolset="core",
    description=(
        "List all current tasks with their status. Use this to see what's "
        "pending, what's in progress, and what's been completed."
    ),
    parameters={"type": "object", "properties": {}},
)
def TaskList() -> str:
    if not _TASKS:
        return "(no tasks)"
    lines: list[str] = []
    for tid, t in sorted(_TASKS.items(), key=lambda kv: int(kv[0])):
        marker = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(t.status, "[?]")
        lines.append(f"  #{tid} {marker} {t.subject}")
        if t.description and t.description != t.subject:
            lines.append(f"        {t.description}")
    return "\n".join(lines)
