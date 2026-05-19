"""Legacy OpenAI ``function_call`` format.

Used by ``gpt-3.5-turbo-0613`` and ``gpt-4-0613``. A single function
call lives on ``raw_response.message.function_call`` as
``{"name": str, "arguments": str_or_dict}``. The newer ``tool_calls``
array (parsed by :mod:`openai_tools`) is what everything ≥ 2024 emits.

Falls back to ``(content, [])`` when the legacy field isn't present.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


def parse(content: str, raw_response: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    msg = raw_response.get("message") if isinstance(raw_response, dict) else None
    if not isinstance(msg, dict):
        return content, []
    fc = msg.get("function_call")
    if not isinstance(fc, dict):
        return content, []
    name = fc.get("name") or ""
    if not isinstance(name, str) or not name:
        return content, []
    raw_args = fc.get("arguments")
    if isinstance(raw_args, dict):
        args: dict[str, Any] = raw_args
    elif isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args) if raw_args.strip() else {}
            args = parsed if isinstance(parsed, dict) else {"_raw": raw_args}
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
    else:
        args = {}
    return content, [{"name": name, "arguments": args, "id": ""}]


register("openai", "gpt-3.5*", parse)
register("openai", "gpt-4-0613", parse)
