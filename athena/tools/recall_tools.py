"""Recall tools: search prior session messages.

Reads the active agent's :class:`~athena.sessions.store.SessionStore` so the
model can pull turns from earlier conversations into its current context.
Filters to the active workspace by default so recall from other projects
doesn't pollute the result.
"""

from __future__ import annotations

from typing import Any, cast

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
        "Search prior session messages. Three modes: keyword (FTS5), "
        "semantic (embedding cosine), hybrid (RRF fusion of both — "
        "default, best on paraphrased queries). Returns the matching "
        "turns with surrounding context (1 turn before, 1 after). "
        'Filters to the active workspace by default — pass workspace="" '
        "to search globally."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query text. For keyword mode, FTS5 syntax (quotes for phrases) applies.",
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
            "mode": {
                "type": "string",
                "enum": ["keyword", "semantic", "hybrid"],
                "description": (
                    "Recall ranker. Defaults to cfg.recall_default_mode "
                    "(usually 'hybrid'). Semantic / hybrid degrade to "
                    "keyword when no embeddings backend is configured."
                ),
            },
        },
        "required": ["query"],
    },
    parallel_safe=True,
)
def search_sessions(
    query: str,
    k: int = 5,
    workspace: str | None = None,
    mode: str | None = None,
) -> str:
    store, active_ws = _store_and_workspace()
    if store is None:
        return "ERROR: search_sessions can only be called from an active agent."
    if workspace is None:
        workspace = active_ws
    elif workspace == "":
        workspace = None  # explicit opt-in to global search

    resolved_mode = _resolve_mode(mode)

    try:
        hits = _ranked_hits(
            store=store, query=query, k=int(k), workspace=workspace, mode=resolved_mode
        )
    except Exception as e:
        return f"ERROR: session search failed: {e}"
    return _format_hits(query, hits)


# ---------------------------------------------------------------------------
# Mode dispatch (T6-01.3)
# ---------------------------------------------------------------------------


def _resolve_mode(mode: str | None) -> str:
    """Pick the effective recall mode. Explicit argument wins;
    else cfg.recall_default_mode; else "hybrid"."""
    if mode in ("keyword", "semantic", "hybrid"):
        return mode
    try:
        from ._active_cfg import active_cfg

        return getattr(active_cfg(), "recall_default_mode", "hybrid") or "hybrid"
    except Exception:
        return "hybrid"


def _ranked_hits(
    *,
    store: Any,
    query: str,
    k: int,
    workspace: str | None,
    mode: str,
) -> list[Any]:
    """Resolve hits per ``mode``. Semantic + hybrid fall back to
    keyword when no vector store is available (no embeddings
    backend), so the caller never breaks because of a missing
    optional component."""
    if mode == "keyword":
        return cast("list[Any]", store.search(query, k=k, workspace=workspace))

    import logging as _logging

    from ..recall import get_active_vector_store, parse_session_doc_id, rrf_fuse

    _log = _logging.getLogger(__name__)

    vector_store = get_active_vector_store()
    if vector_store is None:
        return cast("list[Any]", store.search(query, k=k, workspace=workspace))

    candidate_k = max(k * 3, k + 5)
    # Step bug-fix: the vector store can exist but its embedder
    # can fail at query time (e.g. OllamaProvider has no embed
    # method). Treat that the same as "no vector store" —
    # degrade silently to keyword-only. Otherwise the model
    # sees the error and panics through a tool-loop trying
    # other approaches.
    try:
        vec_doc_ids = vector_store.search(
            query,
            k=candidate_k,
            workspace=workspace,
        )
    except Exception as e:  # noqa: BLE001
        _log.info(
            "search_sessions: vector path unavailable (%s); degrading to keyword-only",
            e,
        )
        return cast("list[Any]", store.search(query, k=k, workspace=workspace))

    if mode == "semantic":
        # Pure semantic: no FTS5 fetch. Hydrate top-k vec ids
        # against the SessionStore. Missing sessions are skipped.
        return [
            hit
            for doc_id in vec_doc_ids[:k]
            for hit in (_hydrate_session_hit(store, doc_id),)
            if hit is not None
        ]

    # Hybrid: FTS5 + vector, fused. Keep the kw hits' SearchHit
    # records as the canonical hydration source — they already
    # have surrounding context + score + started_at from the
    # SessionStore's normal pipeline.
    kw_hits = store.search(query, k=candidate_k, workspace=workspace)
    kw_by_id = {f"{h.session_id}#{h.turn_index}": h for h in kw_hits}
    kw_doc_ids = list(kw_by_id.keys())
    ordered_ids = rrf_fuse(kw_doc_ids, vec_doc_ids)[:k]

    hits: list[Any] = []
    for doc_id in ordered_ids:
        if doc_id in kw_by_id:
            hits.append(kw_by_id[doc_id])
            continue
        # Vector-only id (didn't surface in FTS5) — hydrate from
        # the store using the doc_id parser.
        hit = _hydrate_session_hit(store, doc_id)
        if hit is not None:
            hits.append(hit)
    return hits


def _hydrate_session_hit(store: Any, doc_id: str) -> Any | None:
    """Reconstruct a SearchHit for a doc_id the FTS5 path didn't
    surface. Falls back to ``store.load(session_id)`` + manual
    composition — slower than the FTS5 path, but only triggered
    for vector-only matches in semantic / hybrid mode."""
    from ..recall import parse_session_doc_id

    parsed = parse_session_doc_id(doc_id)
    if parsed is None:
        return None
    session_id, turn_index = parsed
    try:
        messages = store.load(session_id)
    except Exception:  # noqa: BLE001
        return None
    if turn_index < 0 or turn_index >= len(messages):
        return None
    target = messages[turn_index]
    surrounding = [
        {"turn_index": i, **m}
        for i, m in enumerate(messages)
        if turn_index - 1 <= i <= turn_index + 1
    ]
    # Build a SearchHit-shaped object on the spot — the same
    # dataclass the FTS5 path produces, so _format_hits doesn't
    # care which branch produced it.
    from datetime import datetime as _dt

    from ..sessions.store import SearchHit

    content = target.get("content", "")
    if isinstance(content, list):
        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    snippet = (content or "")[:240]
    return SearchHit(
        session_id=session_id,
        turn_index=turn_index,
        role=target.get("role", "?"),
        snippet=snippet,
        surrounding=surrounding,
        score=0.0,
        started_at=_dt.fromtimestamp(0),
        workspace=None,
    )
