"""Memory write/list/delete tools, exposing athena.memory to the model.

R2 stage 3: the model-callable @tool surface now writes through the
profile-keyed provider (``athena.memory.store``) exclusively, scoped
to the active foreground workspace. The Round-4 dual-write to the
legacy ``~/.athena/projects/<slug>/memory/`` location is gone -- the
single store reachable via the provider is the source of truth.

The agent's system-prompt read site (``agent/core.py``) reads from
the same ``(profile, workspace)`` coordinate (R2 stage 2) so writes
land where reads look. MCP server tools and the ``athena memory``
CLI continue to read with ``workspace=None`` (no workspace concept)
-- they see the profile-global view. Workspace-scoped foreground
memories are intentionally invisible from those surfaces; that's
the contract.
"""

from __future__ import annotations

import logging

from ..memory.store import delete_entry, list_entries, write_entry
from . import file_ops  # for current workspace
from .registry import tool

logger = logging.getLogger(__name__)


def _active_profile() -> str:
    """Best-effort lookup of the active agent's profile.

    Falls back to ``"default"`` so a test that bypasses ``Agent``
    construction still gets a usable write target."""
    try:
        from ..agent.core import get_current_agent  # lazy: avoid import cycle
    except ImportError:
        return "default"
    agent = get_current_agent()
    if agent is None:
        return "default"
    return getattr(agent.cfg, "profile", None) or "default"


@tool(
    name="write_memory",
    toolset="memory",
    description=(
        "Save a long-term memory. Use this when the user asks you to "
        "remember something, when they share their role/preferences (type='user'), "
        "when they correct or validate your approach (type='feedback'), when "
        "you learn project context (type='project'), or when they reference "
        "external systems (type='reference'). The MEMORY.md index is "
        "rebuilt automatically. Don't write duplicates — check existing "
        "memories with list_memories first."
    ),
    parameters={
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Short snake_case filename, e.g. 'user_role' or 'feedback_testing'.",
            },
            "name": {"type": "string", "description": "Short title for the memory."},
            "description": {
                "type": "string",
                "description": "One-line description used to decide relevance.",
            },
            "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
            "body": {
                "type": "string",
                "description": "Memory content. For feedback/project, structure as: rule, **Why:**, **How to apply:**.",
            },
        },
        "required": ["filename", "name", "description", "type", "body"],
    },
)
def write_memory(filename: str, name: str, description: str, type: str, body: str) -> str:
    try:
        path = write_entry(
            _active_profile(),
            filename=filename,
            name=name,
            description=description,
            type=type,
            body=body,
            write_origin="foreground",
            workspace=file_ops._WORKSPACE,
        )
    except ValueError as e:
        return f"ERROR: {e}"
    return f"saved memory: {path}"


@tool(
    name="list_memories",
    toolset="memory",
    description="List all memory files for the current workspace, with their type and description.",
    parameters={"type": "object", "properties": {}},
    parallel_safe=True,
)
def list_memories() -> str:
    entries = list_entries(_active_profile(), workspace=file_ops._WORKSPACE)
    if not entries:
        return "(no memories saved for this workspace)"
    lines: list[str] = []
    for entry in entries:
        filename = entry.path.name if entry.path is not None else f"{entry.name}.md"
        lines.append(f"[{entry.type}] {filename} — {entry.name}")
        if entry.description:
            lines.append(f"  {entry.description}")
    return "\n".join(lines)


@tool(
    name="delete_memory",
    toolset="memory",
    description="Delete a memory file by filename. Use when the user asks you to forget something.",
    parameters={
        "type": "object",
        "properties": {"filename": {"type": "string"}},
        "required": ["filename"],
    },
)
def delete_memory(filename: str) -> str:
    # Pass the filename through as-is; the provider resolves by filename
    # (the stable id) or frontmatter name and normalizes a missing .md.
    deleted = delete_entry(
        _active_profile(),
        filename,
        workspace=file_ops._WORKSPACE,
    )
    if deleted:
        return f"deleted {filename}"
    return f"ERROR: {filename} not found"
