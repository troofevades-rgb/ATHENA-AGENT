"""Bare-JSON content recovery.

Models that don't speak any tool-calling protocol at all (truly bare
OpenAI-compat backends, or models served outside their training
template) sometimes emit a single JSON object as their entire
response::

    {"name": "Read", "arguments": {"file_path": "/etc/hostname"}}

This parser conservatively recovers that one case. It does NOT scan
for embedded JSON inside prose — that would mangle legitimate
documentation. Only treats the whole content as a tool call when:

- ``content.strip()`` is a valid JSON object,
- with a non-empty string ``name``,
- and an ``arguments`` value (dict, JSON string, or absent).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .fallback import _coerce_arguments

logger = logging.getLogger(__name__)


def parse(content: str, raw_response: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(content, str):
        return "", []
    stripped = content.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return content, []
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return content, []
    if not isinstance(obj, dict):
        return content, []
    name = obj.get("name")
    if not isinstance(name, str) or not name:
        return content, []
    return "", [
        {
            "name": name,
            "arguments": _coerce_arguments(obj.get("arguments")),
            "id": obj.get("id", "") if isinstance(obj.get("id", ""), str) else "",
        }
    ]
