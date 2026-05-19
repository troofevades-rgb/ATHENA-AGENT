"""Last-resort parser when no (provider, model) entry matched.

Two responsibilities:

- If the raw response has native tool_calls in any common shape
  (``raw["tool_calls"]`` or ``raw["message"]["tool_calls"]``),
  surface them in the canonical ``{name, arguments, id}`` form.
- Otherwise return ``(content, [])`` — let the agent's text-recovery
  layer (the existing ``_extract_text_tool_calls`` in
  ``athena/agent/core.py``) take another swing at it.

Conservative: never invents tool calls from prose. The parser must
not raise.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def fallback_parser(content: str, raw_response: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Return native tool calls when present; otherwise pass content
    through unchanged."""
    try:
        native = _native_tool_calls(raw_response)
    except Exception:  # extremely defensive — parser MUST NOT raise
        logger.debug("fallback_parser: native extraction failed", exc_info=True)
        native = []
    return content, native


def _native_tool_calls(raw_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull tool_calls out of any of the common locations and normalize
    to ``{name, arguments, id}``."""
    if not isinstance(raw_response, dict):
        return []
    candidates: list[Any] = []
    if isinstance(raw_response.get("tool_calls"), list):
        candidates = raw_response["tool_calls"]
    elif isinstance(raw_response.get("message"), dict):
        msg = raw_response["message"]
        if isinstance(msg.get("tool_calls"), list):
            candidates = msg["tool_calls"]
    out: list[dict[str, Any]] = []
    for tc in candidates:
        if not isinstance(tc, dict):
            continue
        # Two shapes in the wild:
        # 1. {"name": ..., "arguments": ..., "id": ...}
        # 2. {"id": ..., "function": {"name": ..., "arguments": ...}}
        if "function" in tc and isinstance(tc["function"], dict):
            fn = tc["function"]
            name = fn.get("name") or ""
            args = fn.get("arguments")
            tc_id = tc.get("id", "")
        else:
            name = tc.get("name") or ""
            args = tc.get("arguments")
            tc_id = tc.get("id", "")
        if not isinstance(name, str) or not name:
            continue
        out.append(
            {
                "name": name,
                "arguments": _coerce_arguments(args),
                "id": tc_id if isinstance(tc_id, str) else "",
            }
        )
    return out


def _coerce_arguments(args: Any) -> dict[str, Any]:
    """Ensure arguments come back as a dict. JSON string → parse;
    dict → pass through; anything else → empty."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        s = args.strip()
        if not s:
            return {}
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else {"_raw": s}
        except json.JSONDecodeError:
            return {"_raw": s}
    return {}
