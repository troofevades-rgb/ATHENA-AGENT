"""Memory write/list/delete tools, exposing athena.memory to the model."""

from __future__ import annotations

from ..memory import (
    delete_memory as _delete,
)
from ..memory import (
    list_memories as _list,
)
from ..memory import (
    write_memory as _write,
)
from . import file_ops  # for current workspace
from .registry import tool


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
        path = _write(
            file_ops._WORKSPACE,
            filename=filename,
            name=name,
            description=description,
            type=type,
            body=body,
        )
    except ValueError as e:
        return f"ERROR: {e}"
    return f"saved memory: {path}"


@tool(
    name="list_memories",
    toolset="memory",
    description="List all memory files for the current workspace, with their type and description.",
    parameters={"type": "object", "properties": {}},
)
def list_memories() -> str:
    mems = _list(file_ops._WORKSPACE)
    if not mems:
        return "(no memories saved for this workspace)"
    lines = []
    for mf in mems:
        lines.append(f"[{mf.type}] {mf.path.name} — {mf.name}")
        if mf.description:
            lines.append(f"  {mf.description}")
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
    if _delete(file_ops._WORKSPACE, filename):
        return f"deleted {filename}"
    return f"ERROR: {filename} not found"
