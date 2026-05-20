"""Translate between OpenAI Chat Completions and Anthropic Messages formats.

Two functions matter:

- :func:`openai_request_to_anthropic` — convert an incoming OpenAI
  ``/v1/chat/completions`` request body into an Anthropic
  ``/v1/messages`` request body.
- :func:`anthropic_stream_to_openai_chunks` — synchronous generator
  that takes Anthropic stream events and yields OpenAI-format SSE
  chunks (strings ready to write to the HTTP response, including
  the ``data: `` prefix and ``\\n\\n`` separator).

The transforms are mostly mechanical: message-role passthrough,
content-shape conversion (string ↔ list of blocks), tool-call format
swap. Edge cases (the ``role=='tool'`` → ``tool_result`` block fold,
assistant messages carrying both text and ``tool_use`` blocks) are
the bits where third-party clients trip over subtle bugs, so the
tests in ``tests/proxy/test_translator.py`` spend extra time on
those paths.

The spec called for async generators but athena's provider surface
is sync (``Iterator[StreamChunk]``); the server bridges to async
SSE at the FastAPI boundary, so keeping the translator itself sync
makes it ordinary-function testable.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterable, Iterator
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAI → Anthropic request translation
# ---------------------------------------------------------------------------


def openai_request_to_anthropic(req: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI Chat Completions request to Anthropic Messages.

    Differences handled:

    - OpenAI's ``messages`` includes the system message in-line with
      ``role="system"``; Anthropic has a top-level ``system`` field.
      Multiple system messages concatenate with a blank line between.
    - OpenAI ``tools`` and Anthropic ``tools`` differ in schema: OpenAI
      wraps each in ``{"type": "function", "function": {...}}``;
      Anthropic uses the inner dict directly with ``input_schema``
      instead of ``parameters``.
    - OpenAI ``tool_choice`` has four forms (``auto``, ``required``,
      ``none``, ``{"type":"function","function":{"name":...}}``)
      mapped to Anthropic's ``auto`` / ``any`` / ``none`` / ``tool``.
    - OpenAI tool-call result messages have ``role="tool"`` with a
      single content string and a ``tool_call_id``; Anthropic uses
      ``role="user"`` with a content list containing ``tool_result``
      blocks. Multiple consecutive ``role="tool"`` messages fold into
      one user message with multiple tool_result blocks.
    """
    messages_in: list[dict[str, Any]] = req.get("messages", []) or []
    system_parts: list[str] = []
    messages_out: list[dict[str, Any]] = []

    pending_tool_results: list[dict[str, Any]] = []

    def _flush_tool_results() -> None:
        if pending_tool_results:
            messages_out.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results.clear()

    for msg in messages_in:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                if content:
                    system_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        system_parts.append(block["text"])
            continue

        if role == "tool":
            # Buffer tool results; they fold into the next user
            # message as content blocks. Anthropic rejects bare
            # role="tool" entries.
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content if isinstance(content, str) else json.dumps(content),
                }
            )
            continue

        # Any non-tool message after a run of tool results flushes
        # them first.
        _flush_tool_results()

        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if content:
                blocks.append({"type": "text", "text": str(content)})
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {}) or {}
                raw_args = fn.get("arguments", "{}")
                try:
                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (TypeError, ValueError):
                    # Anthropic accepts an object; on malformed JSON
                    # we hand it the raw string under "_raw" so the
                    # bug surfaces upstream rather than silently
                    # dropping the tool call.
                    parsed_args = {"_raw": raw_args}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                        "name": fn.get("name", ""),
                        "input": parsed_args,
                    }
                )
            messages_out.append({"role": "assistant", "content": blocks})
            continue

        # Default: pass through. Content may be a string or a list of
        # content blocks (text / image_url / ...); both shapes are
        # valid Anthropic input.
        messages_out.append({"role": role, "content": content})

    # Trailing tool results still pending.
    _flush_tool_results()

    out: dict[str, Any] = {
        "model": req.get("model"),
        "messages": messages_out,
        "max_tokens": int(req.get("max_tokens", 4096)),
    }
    if system_parts:
        out["system"] = "\n\n".join(system_parts)
    if "temperature" in req:
        out["temperature"] = req["temperature"]
    if "top_p" in req:
        out["top_p"] = req["top_p"]
    if "stop" in req and req["stop"] is not None:
        stop = req["stop"]
        out["stop_sequences"] = stop if isinstance(stop, list) else [stop]
    if "tools" in req and req["tools"]:
        out["tools"] = _translate_tools_openai_to_anthropic(req["tools"])
    if "tool_choice" in req:
        out["tool_choice"] = _translate_tool_choice_openai_to_anthropic(req["tool_choice"])
    if req.get("stream"):
        out["stream"] = True

    return out


def _translate_tools_openai_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools or []:
        if tool.get("type") == "function":
            fn = tool.get("function", {}) or {}
            out.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
    return out


def _translate_tool_choice_openai_to_anthropic(choice: Any) -> dict[str, Any]:
    if choice == "auto":
        return {"type": "auto"}
    if choice == "required":
        return {"type": "any"}
    if choice == "none":
        # Anthropic doesn't have a "none" option in 2023-06-01; the
        # closest behaviour is to omit tools entirely. We return the
        # explicit "none" so the server layer can decide whether to
        # strip tools or trust Anthropic to honour a future schema.
        return {"type": "none"}
    if isinstance(choice, dict) and choice.get("type") == "function":
        return {"type": "tool", "name": choice.get("function", {}).get("name", "")}
    return {"type": "auto"}


# ---------------------------------------------------------------------------
# Anthropic stream → OpenAI SSE chunks
# ---------------------------------------------------------------------------


def anthropic_stream_to_openai_chunks(
    stream: Iterable[dict[str, Any]] | Iterator[dict[str, Any]],
    *,
    model: str,
    request_id: str,
) -> Iterator[str]:
    """Translate Anthropic stream events to OpenAI Chat Completions
    SSE chunks. Yields strings ready to write to the response.

    Anthropic event types handled:

    - ``message_start`` — informational; we emit an OpenAI ``role``
      chunk regardless of whether this event arrives.
    - ``content_block_start`` (``text`` or ``tool_use``) — emits a
      preamble chunk announcing a new tool call when applicable.
    - ``content_block_delta`` (``text_delta`` or ``input_json_delta``)
      — emits incremental ``content`` or
      ``tool_calls[i].function.arguments`` chunks.
    - ``content_block_stop`` — no chunk; the OpenAI format folds the
      boundary into the next start.
    - ``message_delta`` (with ``stop_reason``) — emits the final
      ``finish_reason`` chunk.
    - ``message_stop`` — terminator; emits ``data: [DONE]\\n\\n``.

    Output strings already include ``data: `` prefix and ``\\n\\n``
    separator.
    """
    created = int(time.time())

    # Emit the opening role chunk unconditionally. Real Anthropic
    # streams start with ``message_start`` then ``content_block_*``;
    # OpenAI clients expect the role on the first chunk.
    yield _sse_chunk(
        {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
    )

    active_tool_calls: dict[int, dict[str, Any]] = {}
    saw_message_stop = False

    for event in stream:
        etype = event.get("type")

        if etype == "content_block_start":
            index = int(event.get("index", 0))
            block = event.get("content_block", {}) or {}
            if block.get("type") == "tool_use":
                active_tool_calls[index] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                }
                yield _sse_chunk(
                    {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": index,
                                            "id": active_tool_calls[index]["id"],
                                            "type": "function",
                                            "function": {
                                                "name": active_tool_calls[index]["name"],
                                                "arguments": "",
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )

        elif etype == "content_block_delta":
            delta = event.get("delta", {}) or {}
            index = int(event.get("index", 0))
            dtype = delta.get("type")

            if dtype == "text_delta":
                yield _sse_chunk(
                    {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": delta.get("text", "")},
                                "finish_reason": None,
                            }
                        ],
                    }
                )

            elif dtype == "input_json_delta":
                partial = delta.get("partial_json", "")
                yield _sse_chunk(
                    {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": index,
                                            "function": {"arguments": partial},
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )

        elif etype == "message_delta":
            stop_reason = (event.get("delta", {}) or {}).get("stop_reason")
            if stop_reason:
                yield _sse_chunk(
                    {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": _translate_finish_reason(stop_reason),
                            }
                        ],
                    }
                )

        elif etype == "message_stop":
            saw_message_stop = True
            break

    yield "data: [DONE]\n\n"
    if not saw_message_stop:
        # Not strictly an error — some Anthropic streams end without
        # an explicit ``message_stop`` if the connection was closed
        # cleanly mid-stream. Log at debug so a misbehaving upstream
        # is visible without spamming production logs.
        logger.debug("anthropic stream %s ended without message_stop event", request_id)


def _translate_finish_reason(anthropic_stop_reason: str) -> str:
    return {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }.get(anthropic_stop_reason, "stop")


def _sse_chunk(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


# ---------------------------------------------------------------------------
# Non-streaming Anthropic response → OpenAI response
# ---------------------------------------------------------------------------


def anthropic_response_to_openai(
    resp: dict[str, Any], *, model: str, request_id: str
) -> dict[str, Any]:
    """Convert a complete Anthropic ``/v1/messages`` response body to an
    OpenAI ``/v1/chat/completions`` response body (non-streaming).

    Mirrors :func:`anthropic_stream_to_openai_chunks` but for the full
    body — text blocks join into ``message.content``, ``tool_use``
    blocks become ``message.tool_calls`` entries.
    """
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in resp.get("content", []) or []:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                }
            )

    message: dict[str, Any] = {"role": "assistant"}
    if text_parts:
        message["content"] = "".join(text_parts)
    else:
        message["content"] = None
    if tool_calls:
        message["tool_calls"] = tool_calls

    finish = _translate_finish_reason(resp.get("stop_reason") or "end_turn")

    usage = resp.get("usage", {}) or {}
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": int(usage.get("input_tokens", 0)),
            "completion_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
        },
    }
