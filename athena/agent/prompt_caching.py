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

    The original list and message dicts are NOT mutated. Returns a
    deepcopy with markers attached at:
      - The last (or only) system message.
      - The last 3 non-system messages.

    Strategy ``"none"`` returns a deepcopy unchanged. Strategy
    ``"aggressive"`` is currently identical to ``"system_and_3"`` —
    reserved for future strategies (e.g., every-N-turns).

    Pass ``native_anthropic=False`` when the wire format is
    OpenAI-compatible (OpenRouter, Nous Portal); the marker shape is
    the same but lands on the message rather than wrapping the content.
    """
    if strategy == "none":
        return copy.deepcopy(messages)

    if not messages:
        return []

    out = copy.deepcopy(messages)
    marker = _cache_marker(ttl)

    # Find the last system message and mark it.
    last_system_idx = -1
    for i, msg in enumerate(out):
        if msg.get("role") == "system":
            last_system_idx = i
    if last_system_idx >= 0:
        _apply_cache_marker(out[last_system_idx], marker, native_anthropic=native_anthropic)

    # Mark the last 3 non-system messages.
    non_system_indices = [i for i, msg in enumerate(out) if msg.get("role") != "system"]
    for idx in non_system_indices[-3:]:
        _apply_cache_marker(out[idx], marker, native_anthropic=native_anthropic)

    return out


def strip_cache_markers(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove ``cache_control`` from every message and content block.

    Useful for logging, session-store persistence, or routing through
    a provider that doesn't support the markers.
    """
    out = copy.deepcopy(messages)
    for msg in out:
        msg.pop("cache_control", None)
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
    return out
