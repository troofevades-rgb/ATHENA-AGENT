"""Recover tool calls emitted as fenced JSON blocks.

Some models — particularly when running through openai-compat servers
without proper tool-calling support — fall back to emitting tool calls
as code-fenced JSON::

    Here's what I'll do:

    ```json
    {"name": "Read", "arguments": {"file_path": "/etc/hostname"}}
    ```

Conservative: only treats a fence as a tool call if the JSON parses
AND has a non-empty ``name`` string AND ``arguments`` is either a dict
or a JSON string that parses to a dict.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .fallback import _coerce_arguments

logger = logging.getLogger(__name__)


_FENCE_RE = re.compile(
    r"```(?:json|tool_call)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)


def parse(content: str, raw_response: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(content, str):
        return "", []

    tool_calls: list[dict[str, Any]] = []
    cleaned_parts: list[str] = []
    last_end = 0
    for m in _FENCE_RE.finditer(content):
        block = m.group(1)
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            # Not parseable; leave the fence in cleaned content.
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if not isinstance(name, str) or not name:
            continue
        # The block looks like a tool call — strip it from content.
        cleaned_parts.append(content[last_end : m.start()])
        tool_calls.append(
            {
                "name": name,
                "arguments": _coerce_arguments(obj.get("arguments")),
                "id": obj.get("id", "") if isinstance(obj.get("id", ""), str) else "",
            }
        )
        last_end = m.end()
    cleaned_parts.append(content[last_end:])
    cleaned = "".join(cleaned_parts).strip()
    return cleaned, tool_calls
