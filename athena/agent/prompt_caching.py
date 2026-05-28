"""Anthropic prompt caching strategy.

Single layout: ``system_and_3``. 4 ``cache_control`` breakpoints — the
last system message + the last 3 non-system messages, all at the
same TTL.

Reduces input-token costs by ~60-75% on multi-turn conversations
within a single session. With ``ttl="1h"``, costs extend across
sessions that hit the cache within the hour.

Pure functions — no class state, no Agent dependency.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

CacheStrategy = Literal["none", "system_and_3", "aggressive"]
CacheTTL = Literal["5m", "1h"]


def _cache_marker(ttl: CacheTTL) -> dict[str, Any]:
    """Build the cache_control marker dict for the given TTL."""
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}  # 5m default


def _apply_cache_marker(
    msg: dict[str, Any],
    cache_marker: dict[str, Any],
    *,
    native_anthropic: bool = True,
) -> None:
    """Add cache_control to a single message, handling all format variations.

    Anthropic accepts cache_control either on the message itself or on
    a content block. OpenAI-compat routes through an alternate layout.
    Cases handled:

    - tool-role message: marker on the message object (native_anthropic
      only; OpenAI-compat tool messages don't take markers per spec).
    - empty string content: marker on the message object.
    - string content: wrap in a single text block, marker on the block.
    - list content: marker on the last block.
    """
    role = msg.get("role", "")
    content = msg.get("content")

    if role == "tool":
        if native_anthropic:
            msg["cache_control"] = cache_marker
        return

    if content is None or content == "":
        msg["cache_control"] = cache_marker
        return

    if isinstance(content, str):
        msg["content"] = [{"type": "text", "text": content, "cache_control": cache_marker}]
        return

    if isinstance(content, list) and content:
        last = content[-1]
        if isinstance(last, dict):
            last["cache_control"] = cache_marker
        return

    # Defensive: unknown shape -> attach to the message itself.
    msg["cache_control"] = cache_marker


def apply_cache_markers(
    messages: list[dict[str, Any]],
    *,
    strategy: CacheStrategy = "system_and_3",
    ttl: CacheTTL = "5m",
    native_anthropic: bool = True,
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with cache_control markers applied.

    The original list and the individual message dicts are NOT mutated.
    Returns a SHALLOW copy of the list in which only the messages that
    actually receive a marker are deep-copied (up to 4: the last system
    message + the last 3 non-system messages). Messages NOT in those
    positions are aliased with the caller -- safe because this function
    doesn't mutate them and the marker-application step targets only
    the deep-copied indices.

    Strategy ``"none"`` returns a FULL deepcopy so callers that opt out
    of caching can still rely on isolated copy semantics. Strategy
    ``"aggressive"`` is currently identical to ``"system_and_3"`` --
    reserved for future strategies (e.g., every-N-turns).

    Pass ``native_anthropic=False`` when the wire format is
    OpenAI-compatible (OpenRouter, Nous Portal); the marker shape is
    the same but lands on the message rather than wrapping the content.
    """
    if strategy == "none":
        return copy.deepcopy(messages)

    if not messages:
        return []

    marker = _cache_marker(ttl)

    # Identify which message indices will receive a marker: the last
    # system message (if any) plus the last 3 non-system messages.
    last_system_idx = -1
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            last_system_idx = i
    non_system_indices = [i for i, msg in enumerate(messages) if msg.get("role") != "system"]

    marked_indices: set[int] = set(non_system_indices[-3:])
    if last_system_idx >= 0:
        marked_indices.add(last_system_idx)

    # Shallow-copy the outer list; deep-copy only the ~4 messages that
    # get mutated. Other messages are shared with the caller — they're
    # never mutated by the marker application so this is safe.
    out: list[dict[str, Any]] = list(messages)
    for idx in marked_indices:
        out[idx] = copy.deepcopy(messages[idx])
        _apply_cache_marker(out[idx], marker, native_anthropic=native_anthropic)

    return out


def strip_cache_markers(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove ``cache_control`` from every message and content block.

    Useful for logging, session-store persistence, or routing through
    a provider that doesn't support the markers. Fast path: if no
    message carries a marker, return a shallow list copy and skip the
    deepcopy entirely — the common case on the persist path.
    """
    def _has_marker(msg: dict[str, Any]) -> bool:
        if "cache_control" in msg:
            return True
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    return True
        return False

    if not any(_has_marker(m) for m in messages):
        return list(messages)

    out = copy.deepcopy(messages)
    for msg in out:
        msg.pop("cache_control", None)
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
    return out
