"""Recall tools: search prior session messages.

Reads the active agent's :class:`~athena.sessions.store.SessionStore` so the
model can pull turns from earlier conversations into its current context.
Filters to the active workspace by default so recall from other projects
doesn't pollute the result.
"""

from __future__ import annotations

from typing import Any

from .registry import tool


def _store_and_workspace() -> tuple[Any | None, str | None]:
    """Resolve the live agent's SessionStore + workspace path.

    Returns (None, None) when no agent is active (e.g. a tool called from a
    unit test without an Agent context). Callers degrade gracefully.
    """
    from ..agent.core import get_current_agent

    agent = get_current_agent()
    if agent is None:
        return None, None
    return getattr(agent, "session_store", None), str(getattr(agent, "workspace", "")) or None


def _format_hits(query: str, hits: list[Any]) -> str:
    if not hits:
        return f"No matches for {query!r}."
    lines = [f"Found {len(hits)} match(es) for {query!r}:", ""]
    for h in hits:
        started = h.started_at.strftime("%Y-%m-%d %H:%M") if h.started_at else "?"
        lines.append(f"## Session {h.session_id} ({started})")
        for ctx in h.surrounding:
            role = ctx.get("role", "?")
            content = ctx.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            content = (content or "").replace("\n", " ").strip()
            if len(content) > 300:
                content = content[:297] + "..."
            marker = "▶" if ctx.get("turn_index") == h.turn_index else " "
            lines.append(f"  {marker} {role}: {content}")
        lines.append("")
    return "\n".join(lines).rstrip()


@tool(
    name="search_sessions",
    toolset="recall",
    description=(
        "Search prior session messages by keyword (FTS5-backed). Returns the "
        "matching turns with surrounding context (1 turn before, 1 after) so "
        "the result has enough shape for you to act on it. Filters to the "
        'active workspace by default — pass workspace="" to search globally.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "FTS5 query string. Use quotes for phrases.",
            },
            "k": {"type": "integer", "description": "Max number of matches (default 5)."},
            "workspace": {
                "type": "string",
                "description": (
                    "Restrict to a specific workspace path. Omit (or pass the "
                    "current workspace) for the default scope; empty string '' "
                    "searches all workspaces."
                ),
            },
        },
        "required": ["query"],
    },
)
def search_sessions(query: str, k: int = 5, workspace: str | None = None) -> str:
    store, active_ws = _store_and_workspace()
    if store is None:
        return "ERROR: search_sessions can only be called from an active agent."
    if workspace is None:
        workspace = active_ws
    elif workspace == "":
        workspace = None  # explicit opt-in to global search

    try:
        hits = store.search(query, k=int(k), workspace=workspace)
    except Exception as e:
        return f"ERROR: session search failed: {e}"
    return _format_hits(query, hits)
