"""Memory write/list/delete tools, exposing athena.memory to the model.

History: the workspace-keyed legacy API (``~/.athena/projects/<slug>/memory/``)
and the profile-keyed provider (``~/.athena/profiles/<profile>/memory/``)
shipped as parallel stores. The model wrote to one, the MCP-side
``query_memory`` server tool and the ``athena memory`` CLI read from the
other -- a cross-surface workflow gap (gateway/cron/webhook agents saw a
different memory set than the foreground REPL).

Until Phase 14 finishes the full migration, the @tool wrappers below
dual-write: each write hits the legacy workspace-keyed location AND the
profile-keyed provider, and reads aggregate from both with dedupe on
filename. This keeps existing data visible while making new writes
visible to MCP / CLI consumers. ``profile`` is sourced from the active
agent's config; when no agent is bound (rare; only happens in tests
that bypass ``Agent``), we fall back to "default".
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


def _active_profile() -> str:
    """Best-effort lookup of the active agent's profile so dual-writes
    land in the right profile-keyed dir. Falls back to "default" so a
    test that never constructs an Agent still gets a usable write."""
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
    # Dual-write to the profile-keyed provider so MCP / CLI consumers
    # see the entry. A provider failure must not break the legacy
    # path -- log and continue. write_origin is "foreground" because
    # the @tool surface is always model-driven.
    try:
        from ..memory.store import write_entry as _write_entry
        _write_entry(
            _active_profile(),
            filename=filename,
            name=name,
            description=description,
            type=type,
            body=body,
            write_origin="foreground",
        )
    except Exception:
        logger.debug("memory_tools.write_memory provider mirror failed", exc_info=True)
    return f"saved memory: {path}"


@tool(
    name="list_memories",
    toolset="memory",
    description="List all memory files for the current workspace, with their type and description.",
    parameters={"type": "object", "properties": {}},
)
def list_memories() -> str:
    seen_filenames: set[str] = set()
    lines: list[str] = []
    for mf in _list(file_ops._WORKSPACE):
        seen_filenames.add(mf.path.name)
        lines.append(f"[{mf.type}] {mf.path.name} — {mf.name}")
        if mf.description:
            lines.append(f"  {mf.description}")
    # Pull entries from the profile-keyed provider too. Dedupe on the
    # filename so dual-written entries don't appear twice; entries that
    # only exist in the new store (e.g. written by a sibling MCP
    # consumer) still show up.
    try:
        from ..memory.store import list_entries
        for entry in list_entries(_active_profile()):
            fname = getattr(entry, "filename", None) or f"{entry.name}.md"
            if fname in seen_filenames:
                continue
            seen_filenames.add(fname)
            lines.append(f"[{entry.type}] {fname} — {entry.name}")
            if entry.description:
                lines.append(f"  {entry.description}")
    except Exception:
        logger.debug("memory_tools.list_memories provider lookup failed", exc_info=True)
    if not lines:
        return "(no memories saved for this workspace)"
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
    legacy_hit = False
    try:
        legacy_hit = _delete(file_ops._WORKSPACE, filename)
    except ValueError as e:
        return f"ERROR: {e}"
    # Also clean up the profile-keyed mirror so a sibling MCP query
    # doesn't keep seeing the deleted entry. Any failure is logged
    # rather than surfaced -- the legacy delete is the contract.
    provider_hit = False
    try:
        from ..memory.store import delete_entry
        name = filename[:-3] if filename.endswith(".md") else filename
        provider_hit = bool(delete_entry(_active_profile(), name))
    except Exception:
        logger.debug("memory_tools.delete_memory provider mirror failed", exc_info=True)
    if legacy_hit or provider_hit:
        return f"deleted {filename}"
    return f"ERROR: {filename} not found"
