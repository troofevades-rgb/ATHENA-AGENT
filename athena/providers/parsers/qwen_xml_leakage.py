"""Qwen models leak tool calls into content as ``<tool_call>{...}</tool_call>``.

Seen in real sessions with ``qwen2.5-coder:14b`` and ``qwen3-coder`` —
the model emits the tool call as XML-wrapped JSON in its content
stream instead of using the provider's native ``tool_calls`` field.
Recover them.

If the raw_response already carries native tool_calls (rare but
possible — Ollama sometimes extracts them), those win and content is
returned unchanged.

Otherwise: scan content for ``<tool_call>{...}</tool_call>`` blocks,
extract each, strip from content, preserve the assistant's natural-
language preamble around them.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import register
from .fallback import _coerce_arguments, _native_tool_calls

logger = logging.getLogger(__name__)


_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)


def parse(
    content: str, raw_response: dict[str, Any]
) -> tuple[str, list[dict[str, Any]]]:
    # If the provider already pulled out native tool_calls, prefer those.
    native = _native_tool_calls(raw_response) if isinstance(raw_response, dict) else []
    if native:
        return content, native

    if not isinstance(content, str):
        return "", []

    tool_calls: list[dict[str, Any]] = []
    cleaned_parts: list[str] = []
    last_end = 0
    for m in _TOOL_CALL_RE.finditer(content):
        cleaned_parts.append(content[last_end:m.start()])
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            # Malformed JSON — leave the original block in cleaned content
            # so the model can see what it emitted on the next turn.
            cleaned_parts.append(m.group(0))
            last_end = m.end()
            continue
        if not isinstance(obj, dict):
            cleaned_parts.append(m.group(0))
            last_end = m.end()
            continue
        name = obj.get("name")
        if not isinstance(name, str) or not name:
            cleaned_parts.append(m.group(0))
            last_end = m.end()
            continue
        tool_calls.append({
            "name": name,
            "arguments": _coerce_arguments(obj.get("arguments")),
            "id": obj.get("id", "") if isinstance(obj.get("id", ""), str) else "",
        })
        last_end = m.end()
    cleaned_parts.append(content[last_end:])
    cleaned = "".join(cleaned_parts).strip()
    return cleaned, tool_calls


# Qwen on every provider it can run on.
register("ollama", "qwen*", parse)
register("ollama", "*qwen*", parse)
register("openai_compat", "qwen*", parse)
register("openai_compat", "*qwen*", parse)
