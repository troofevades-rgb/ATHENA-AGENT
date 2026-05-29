"""Tool: read a previously stored tool result by handle or hash.

The companion to ``tool_result_storage.maybe_store_result``: when
the dispatcher persists a large tool output out-of-band and the
agent sees a ``[tool_result:<hash> — ...]`` handle, this tool
reads back the stored content. Pagination via ``offset`` +
``max_bytes`` lets the agent stream through a multi-megabyte blob
without re-inlining the whole thing.
"""

from __future__ import annotations

from .registry import tool


@tool(
    name="read_tool_result",
    toolset="file",
    description=(
        "Read a previously stored tool result by its handle. When a "
        "tool returns more than ~1MB of output, athena replaces the "
        "raw content with a `[tool_result:<hash> — <size> output "
        "stored. Use read_tool_result to access.]` handle in "
        "conversation history; pass that handle (or just the 16-char "
        "hash) here to read the stored content. Use offset + "
        "max_bytes to page through large blobs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "handle": {
                "type": "string",
                "description": (
                    "The tool_result handle (the bracketed line) or the bare 16-char hex hash."
                ),
            },
            "max_bytes": {
                "type": "integer",
                "description": "Max bytes to read in one call (default 100000).",
            },
            "offset": {
                "type": "integer",
                "description": "Byte offset to start reading from (default 0).",
            },
        },
        "required": ["handle"],
    },
    parallel_safe=True,
)
def read_tool_result(
    handle: str,
    max_bytes: int = 100_000,
    offset: int = 0,
) -> str:
    """Read up to ``max_bytes`` of a stored tool result from ``offset``."""
    from ..agent.core import get_current_agent

    agent = get_current_agent()
    storage = getattr(agent, "tool_result_storage", None) if agent else None
    if storage is None:
        return "ERROR: tool_result_storage not initialised on the current agent"

    try:
        return storage.read(handle, max_bytes=int(max_bytes), offset=int(offset))
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    except ValueError as e:
        return f"ERROR: {e}"
