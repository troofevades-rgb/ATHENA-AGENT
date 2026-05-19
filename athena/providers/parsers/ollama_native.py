"""Ollama's native tool-call format.

Same shape as OpenAI's ``tool_calls`` array — Ollama deliberately
mirrors the OpenAI schema. ``raw_response.message.tool_calls`` is a
list of ``{"function": {"name": str, "arguments": dict_or_str}}``.

Registered as the *provider default* for ollama via ``register_default``.
Model-specific entries (Qwen XML leakage, GPT-OSS harmony, ...) take
priority by virtue of being registered to ``register()`` not
``register_default()`` — every (provider, model_glob) tuple is tried
before defaults.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import register_default

logger = logging.getLogger(__name__)


def parse(content: str, raw_response: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
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
        out.append(
            {
                "name": name,
                "arguments": args,
                "id": tc_id if isinstance(tc_id, str) else "",
            }
        )
    return content, out


register_default("ollama", parse)
