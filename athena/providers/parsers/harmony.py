"""GPT-OSS harmony format.

Three channels separated by special tokens::

    <|channel|>analysis<|message|>internal reasoning...<|end|>
    <|channel|>commentary<|message|>tool call lines here<|end|>
    <|channel|>final<|message|>visible answer<|return|>

- ``analysis``: hidden chain-of-thought; drop entirely.
- ``commentary``: where tool calls go. Lines of the form
  ``ToolName({"arg": "value"})`` become tool_calls.
- ``final``: the assistant's visible response; becomes cleaned_content.

If no ``<|channel|>`` structure is detected, the parser conservatively
returns ``(content, [])`` rather than mangling text from other formats.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import register

logger = logging.getLogger(__name__)


_CHANNEL_RE = re.compile(
    r"<\|channel\|>(\w+)<\|message\|>(.*?)<\|(end|return)\|>",
    re.DOTALL,
)
_TOOL_CALL_LINE_RE = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)$",
    re.DOTALL,
)


def parse(
    content: str, raw_response: dict[str, Any]
) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(content, str):
        return "", []

    matches = list(_CHANNEL_RE.finditer(content))
    if not matches:
        return content, []

    final_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for m in matches:
        channel = m.group(1)
        msg = m.group(2)
        if channel == "final":
            final_parts.append(msg.strip())
        elif channel == "commentary":
            for raw_line in msg.strip().splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                tc_match = _TOOL_CALL_LINE_RE.match(line)
                if not tc_match:
                    continue
                name = tc_match.group(1)
                args_str = tc_match.group(2).strip()
                args: dict[str, Any]
                if not args_str:
                    args = {}
                else:
                    try:
                        parsed = json.loads(args_str)
                        args = parsed if isinstance(parsed, dict) else {"_raw": args_str}
                    except json.JSONDecodeError:
                        args = {"_raw": args_str}
                tool_calls.append({"name": name, "arguments": args, "id": ""})
        # analysis is intentionally dropped — internal reasoning, never
        # surfaced as cleaned content or as a tool call.

    cleaned = "\n\n".join(p for p in final_parts if p).strip()
    return cleaned, tool_calls


# GPT-OSS variants on every provider it can run on.
register("openai", "gpt-oss*", parse)
register("openai_compat", "gpt-oss*", parse)
register("ollama", "gpt-oss*", parse)
register("ollama", "*gpt-oss*", parse)
