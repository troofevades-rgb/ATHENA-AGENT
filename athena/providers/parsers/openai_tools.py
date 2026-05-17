"""Current OpenAI ``tool_calls`` array format.

Used by everything from gpt-4 onwards. Lives on
``raw_response.message.tool_calls`` as a list of
``{"id": str, "type": "function", "function": {"name": str, "arguments": str_or_dict}}``.

Also the wire format for every OpenAI-compatible service: OpenRouter,
Nous Portal, vLLM, llama.cpp's server, TabbyAPI, etc. Registered for
all of those.

Argument values come back as a JSON string from OpenAI (per the spec)
but dict-shaped from some compat servers; we accept both.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from . import register, register_default

logger = logging.getLogger(__name__)


def parse(
    content: str, raw_response: dict[str, Any]
) -> tuple[str, list[dict[str, Any]]]:
    msg = raw_response.get("message") if isinstance(raw_response, dict) else None
    if not isinstance(msg, dict):
        return content, []
    raw_calls = msg.get("tool_calls")
    if not isinstance(raw_calls, list):
        return content, []
    out: list[dict[str, Any]] = []
    for tc in raw_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            continue
        name = fn.get("name") or ""
        if not isinstance(name, str) or not name:
            continue
        raw_args = fn.get("arguments")
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
        tc_id = tc.get("id", "")
        out.append({
            "name": name,
            "arguments": args,
            "id": tc_id if isinstance(tc_id, str) else "",
        })
    return content, out


# Newer OpenAI models. The narrower openai_function entries (registered
# in openai_function.py at module-import time) fire first because the
# parser registry iterates in registration order — importing
# openai_function before openai_tools is what guarantees that.
register("openai", "gpt-4*", parse)
register("openai", "gpt-4o*", parse)
register("openai", "o1*", parse)
register("openai", "o3*", parse)
register("openai", "o4*", parse)
# Every OpenAI-compatible service speaks the same shape. Use
# register_default so model-specific entries (qwen_xml_leakage for
# qwen* on openai_compat, harmony for gpt-oss* on openai/openai_compat)
# fire FIRST and only fall through to this when nothing more specific
# matched. (Mistake of an earlier draft: registering "*" via register()
# caught everything before model-specific globs got a chance.)
register_default("openai", parse)
register_default("openrouter", parse)
register_default("openai_compat", parse)
register_default("nous", parse)
