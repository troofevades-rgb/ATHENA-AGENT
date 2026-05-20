"""Pure StreamChunk → OpenAI Chat Completions translation (T3-01R.2).

Lifted out of ``server.py`` so the wire-format translation is
unit-testable in isolation — no aiohttp, no provider, no I/O. Two
functions matter:

- :func:`stream_chunks_to_openai_sse` — sync generator yielding
  OpenAI SSE strings (``data: {...}\\n\\n`` ... ``data: [DONE]\\n\\n``)
  for the streaming path.
- :func:`collect_chunks_to_openai_response` — drains the iterator
  into a single ``chat.completion`` object for the non-streaming
  path.

StreamChunk kinds map this way:

  content      → choices[0].delta.content (SSE) / message.content (final)
  tool_call    → choices[0].delta.tool_calls[i].function.{name,arguments}
  usage        → top-level usage (final non-streaming object only)
  end          → choices[0].finish_reason (mapped end_turn→stop, etc.)
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from ..providers.base import StreamChunk

# Mapping from athena's raw stop reasons to the OpenAI finish_reason
# vocabulary. Anything we don't recognise defaults to "stop".
_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "stop",
    "end_turn": "stop",
    "length": "length",
    "max_tokens": "length",
    "tool_calls": "tool_calls",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}


def _openai_finish_reason(raw: str) -> str:
    return _FINISH_REASON_MAP.get(raw, "stop")


def _sse(payload: dict[str, Any]) -> str:
    """One SSE frame: ``data: <compact-json>\\n\\n``."""
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def stream_chunks_to_openai_sse(
    chunks: Iterator[StreamChunk],
    *,
    model: str,
    request_id: str,
    on_usage: Callable[[int, int, int], None] | None = None,
) -> Iterator[str]:
    """Translate athena's :class:`StreamChunk` iterator into OpenAI
    Chat Completions SSE strings.

    ``on_usage`` is invoked once for each ``usage`` chunk with
    ``(prompt_tokens, completion_tokens, cache_read_input_tokens)``.
    The server uses this to accumulate token counts for the proxy
    log without re-parsing the SSE bytes.

    The output always starts with a role chunk (OpenAI clients
    expect ``role=assistant`` on the first delta) and always ends
    with ``data: [DONE]\\n\\n``.
    """
    created = int(time.time())
    finish_emitted = False
    tool_index_by_id: dict[str, int] = {}
    next_tool_index = 0

    yield _sse(
        {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
    )

    for chunk in chunks:
        kind = chunk.kind
        payload = chunk.payload

        if kind == "content" and isinstance(payload, str) and payload:
            yield _sse(
                {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": payload},
                            "finish_reason": None,
                        }
                    ],
                }
            )

        elif kind == "tool_call" and isinstance(payload, dict):
            tool_id = str(payload.get("id") or f"call_{uuid.uuid4().hex[:12]}")
            if tool_id not in tool_index_by_id:
                tool_index_by_id[tool_id] = next_tool_index
                next_tool_index += 1
            idx = tool_index_by_id[tool_id]
            raw_args = payload.get("arguments", "")
            args_str = raw_args if isinstance(raw_args, str) else json.dumps(raw_args)
            yield _sse(
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
                                        "index": idx,
                                        "id": tool_id,
                                        "type": "function",
                                        "function": {
                                            "name": str(payload.get("name", "")),
                                            "arguments": args_str,
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )

        elif kind == "usage" and isinstance(payload, dict):
            if on_usage is not None:
                on_usage(
                    int(payload.get("prompt_tokens", 0)),
                    int(payload.get("completion_tokens", 0)),
                    int(payload.get("cache_read_input_tokens", 0)),
                )

        elif kind == "end" and isinstance(payload, dict):
            reason = str(payload.get("reason") or "stop")
            yield _sse(
                {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": _openai_finish_reason(reason),
                        }
                    ],
                }
            )
            finish_emitted = True

    if not finish_emitted:
        # Defensive: some upstream streams terminate without an
        # explicit ``end`` chunk. OpenAI clients want a final
        # ``finish_reason`` set, so synthesise one.
        yield _sse(
            {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        )

    yield "data: [DONE]\n\n"


def collect_chunks_to_openai_response(
    chunks: Iterator[StreamChunk],
    *,
    model: str,
    request_id: str,
) -> dict[str, Any]:
    """Drain a :class:`StreamChunk` iterator and build the
    non-streaming ``chat.completion`` body."""
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    finish: str = "stop"
    prompt_tokens = 0
    completion_tokens = 0

    for chunk in chunks:
        if chunk.kind == "content" and isinstance(chunk.payload, str):
            content_parts.append(chunk.payload)
        elif chunk.kind == "tool_call" and isinstance(chunk.payload, dict):
            args = chunk.payload.get("arguments", "")
            args_str = args if isinstance(args, str) else json.dumps(args)
            tool_calls.append(
                {
                    "id": str(chunk.payload.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                    "type": "function",
                    "function": {
                        "name": str(chunk.payload.get("name", "")),
                        "arguments": args_str,
                    },
                }
            )
        elif chunk.kind == "usage" and isinstance(chunk.payload, dict):
            prompt_tokens = int(chunk.payload.get("prompt_tokens", 0))
            completion_tokens = int(chunk.payload.get("completion_tokens", 0))
        elif chunk.kind == "end" and isinstance(chunk.payload, dict):
            finish = _openai_finish_reason(str(chunk.payload.get("reason") or "stop"))

    message: dict[str, Any] = {"role": "assistant"}
    message["content"] = "".join(content_parts) if content_parts else None
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
