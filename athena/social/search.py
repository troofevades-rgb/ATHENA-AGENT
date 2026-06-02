"""``search_x`` tool — explicit social-search routing (T6-02.3).

The model calls this tool when it wants X / social data. Routing
goes through the T5-01 manifest:

    best_provider_for({"social_search"})

That lookup is the cash-in on T5-01 — no provider-name special-
casing, no hardcoded "if vendor == X". A provider that declares
``social_search=True`` is the one the broker selects; one that
doesn't isn't considered.

The switch is **visible** (printed to the UI via ``ui.info``) and
**logged** (INFO on ``athena.social.search``). The primary chat
model isn't touched — the sub-call goes out, the result folds
back into the primary's tool-result, and the primary reasons over
it.

Graceful when absent: no provider declares ``social_search`` →
the tool returns a structured ``{available: false, reason: ...}``
payload the model can react to. Never raises into the agent
loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .. import ui
from ..tools.registry import tool

logger = logging.getLogger(__name__)


_DEFAULT_MAX_RESULTS = 20


@tool(
    name="search_x",
    aliases=("social_search",),
    toolset="recall",
    description=(
        "Search X / social posts for recent, real-time information. "
        "Use when the user asks what's on X / Twitter / social about "
        "a topic, or wants the latest social discussion. Routes via "
        "the capability manifest to whichever provider declares "
        "social_search — the primary chat model stays selected "
        "throughout; this is a sub-call. Returns normalised results "
        "(author, text, timestamp, url, optional metrics)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — keywords or a short phrase.",
            },
            "max_results": {
                "type": "integer",
                "description": f"Max results to return (default {_DEFAULT_MAX_RESULTS}).",
            },
        },
        "required": ["query"],
    },
    parallel_safe=True,
)
def search_x(
    query: str = "",
    max_results: int | None = None,
    **_kwargs: Any,
) -> str:
    """Search-x tool entry. Returns JSON-formatted text that the
    model parses as the tool result.

    The return shape is::

        {
          "available": bool,
          "provider": str | null,
          "results": [
            {"author", "text", "timestamp", "url", "metrics"?},
            ...
          ],
          "reason": str | null   # populated when available=false
        }

    JSON gives the model a structured, predictable surface; the
    tool result text format is intentionally identical regardless
    of which vendor's behind it.
    """
    if not query or not str(query).strip():
        return _payload(available=False, reason="empty query")
    n = int(max_results) if max_results else _resolve_default_max_results()

    provider_name, provider = _resolve_social_provider()
    if provider is None:
        logger.info("search_x: no social_search provider available; degraded")
        return _payload(available=False, reason="no social-search provider configured")

    # Visible switch + log — the user / operator should never
    # wonder which backend ran the search.
    ui.info(f"searching X via {provider_name}")
    logger.info("search_x: routing query=%r to provider=%r", query, provider_name)

    try:
        results = provider.social_search(query, max_results=n)
    except Exception as e:  # noqa: BLE001
        logger.warning("search_x: provider raised: %s", e)
        return _payload(
            available=False,
            provider=provider_name,
            reason=f"provider failed: {e}",
        )

    return _payload(available=True, provider=provider_name, results=results or [])


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_social_provider() -> tuple[str | None, Any]:
    """Find the best provider declaring social_search.

    Goes through :func:`athena.providers.best_provider_for`
    (T5-01) so the lookup matches the manifest's design — class-
    level capability declaration drives routing.

    Returns ``(provider_name, provider_instance)``; either both
    None (no declared provider OR construction failed) or both
    set.

    A provider that declares ``social_search`` but isn't
    available right now (e.g. no OAuth token) returns
    ``(name, None)`` — the caller treats that as "configured but
    not ready" and surfaces the reason.
    """
    from ..providers import best_provider_for, get_provider_class

    name = best_provider_for({"social_search"})
    if name is None:
        return None, None
    cls = get_provider_class(name)
    try:
        instance = cls()
    except Exception as e:  # noqa: BLE001
        logger.warning("search_x: could not instantiate social provider %r: %s", name, e)
        return name, None

    is_available_fn = getattr(instance, "is_available", None)
    if callable(is_available_fn):
        try:
            if not is_available_fn():
                logger.info(
                    "search_x: provider %r declared but not available (token missing?)",
                    name,
                )
                return name, None
        except Exception as e:  # noqa: BLE001
            logger.warning("search_x: is_available raised on %r: %s", name, e)
            return name, None
    return name, instance


def _resolve_default_max_results() -> int:
    try:
        from ..config import load_config

        return int(getattr(load_config(), "social_search_max_results", _DEFAULT_MAX_RESULTS))
    except Exception:  # noqa: BLE001
        return _DEFAULT_MAX_RESULTS


def _payload(
    *,
    available: bool,
    provider: str | None = None,
    results: list[dict[str, Any]] | None = None,
    reason: str | None = None,
) -> str:
    """Render the tool result payload. Keeps the JSON shape
    identical regardless of branch so the model can rely on the
    keys it sees."""
    body = {
        "available": bool(available),
        "provider": provider,
        "results": list(results or []),
        "reason": reason,
    }
    return json.dumps(body, ensure_ascii=False)
