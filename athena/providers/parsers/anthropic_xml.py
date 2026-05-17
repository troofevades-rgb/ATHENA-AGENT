"""Anthropic content-block parser.

Anthropic's ``/v1/messages`` returns a content array of blocks:

    [
      {"type": "text",     "text": "I'll read that file."},
      {"type": "tool_use", "id": "tu_01...", "name": "Read",
       "input": {"file_path": "/etc/hostname"}},
    ]

Streaming already extracts tool_use blocks via ``content_block_start``
+ ``input_json_delta`` accumulation (see athena/providers/anthropic.py),
so by the time ``parse_tool_calls`` runs the heavy lifting is done.
This parser handles the non-streaming case (when raw_response has the
full content array): text blocks join into cleaned_content; tool_use
blocks become tool_calls.

Falls back to the global fallback parser's behavior when raw_response
doesn't carry an Anthropic content array.
"""
from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


def parse(
    content: str, raw_response: dict[str, Any]
) -> tuple[str, list[dict[str, Any]]]:
    """Extract text and tool_use blocks from Anthropic's content array.

    If raw_response doesn't carry a content array (common when only
    streaming chunks were stitched together), returns ``(content, [])``
    — the streaming path already pulled out the tool_calls.
    """
    blocks = raw_response.get("content") if isinstance(raw_response, dict) else None
    if not isinstance(blocks, list):
        return content, []

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            if isinstance(text, str):
                text_parts.append(text)
        elif btype == "tool_use":
            name = block.get("name") or ""
            if not isinstance(name, str) or not name:
                continue
            input_args = block.get("input") or {}
            if not isinstance(input_args, dict):
                input_args = {"_raw": str(input_args)}
            tc_id = block.get("id", "")
            tool_calls.append({
                "name": name,
                "arguments": input_args,
                "id": tc_id if isinstance(tc_id, str) else "",
            })
    cleaned = "".join(text_parts).strip()
    return cleaned, tool_calls


register("anthropic", "claude-*", parse)
