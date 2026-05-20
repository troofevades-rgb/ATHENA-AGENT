"""Tests for athena.proxy.translator (T3-01.2).

Sync tests. The translator is the most-trafficked piece of the
proxy — every third-party request flows through it — so the tests
cover both directions exhaustively, with extra weight on tool-call
translation (where subtle bugs hide).
"""

from __future__ import annotations

import json
from typing import Any

from athena.proxy.translator import (
    _translate_finish_reason,
    anthropic_response_to_openai,
    anthropic_stream_to_openai_chunks,
    openai_request_to_anthropic,
)

# ---------------------------------------------------------------------------
# OpenAI request → Anthropic request
# ---------------------------------------------------------------------------


def test_basic_user_message_translated() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hello"}],
    }
    out = openai_request_to_anthropic(req)
    assert out["model"] == "claude-sonnet-4-6"
    assert out["messages"] == [{"role": "user", "content": "hello"}]
    assert "system" not in out
    assert out["max_tokens"] == 4096  # default


def test_system_message_extracted_to_top_level() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ],
    }
    out = openai_request_to_anthropic(req)
    assert out["system"] == "be terse"
    # System message should NOT appear in messages
    assert all(m["role"] != "system" for m in out["messages"])
    assert out["messages"] == [{"role": "user", "content": "hi"}]


def test_multi_system_messages_concatenated() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "first"},
            {"role": "system", "content": "second"},
            {"role": "user", "content": "hi"},
        ],
    }
    out = openai_request_to_anthropic(req)
    assert out["system"] == "first\n\nsecond"


def test_assistant_with_tool_calls_translates_to_tool_use_blocks() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "user", "content": "do thing"},
            {
                "role": "assistant",
                "content": "calling tool",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "do_thing",
                            "arguments": '{"x": 1, "y": "z"}',
                        },
                    }
                ],
            },
        ],
    }
    out = openai_request_to_anthropic(req)
    assistant = out["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "text", "text": "calling tool"}
    assert assistant["content"][1] == {
        "type": "tool_use",
        "id": "call_abc",
        "name": "do_thing",
        "input": {"x": 1, "y": "z"},
    }


def test_role_tool_message_folds_into_next_user_with_tool_result() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "user", "content": "do thing"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "do_thing", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_abc", "content": "result data"},
        ],
    }
    out = openai_request_to_anthropic(req)
    # The trailing tool result must fold into a user message with
    # a tool_result block.
    last = out["messages"][-1]
    assert last["role"] == "user"
    assert last["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call_abc",
            "content": "result data",
        }
    ]


def test_multiple_tool_results_fold_into_one_user_message() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "tool", "tool_call_id": "t1", "content": "r1"},
            {"role": "tool", "tool_call_id": "t2", "content": "r2"},
            {"role": "user", "content": "next"},
        ],
    }
    out = openai_request_to_anthropic(req)
    # Folded user message comes first; then the next user message.
    assert out["messages"][0]["role"] == "user"
    assert len(out["messages"][0]["content"]) == 2
    assert out["messages"][0]["content"][0]["tool_use_id"] == "t1"
    assert out["messages"][0]["content"][1]["tool_use_id"] == "t2"
    assert out["messages"][1] == {"role": "user", "content": "next"}


def test_tools_array_unwraps_function_wrapper() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "look up weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ],
    }
    out = openai_request_to_anthropic(req)
    assert out["tools"] == [
        {
            "name": "get_weather",
            "description": "look up weather",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        }
    ]


def test_tool_choice_auto_required_none_specific() -> None:
    base: dict[str, Any] = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert openai_request_to_anthropic({**base, "tool_choice": "auto"})["tool_choice"] == {
        "type": "auto"
    }
    assert openai_request_to_anthropic({**base, "tool_choice": "required"})["tool_choice"] == {
        "type": "any"
    }
    assert openai_request_to_anthropic({**base, "tool_choice": "none"})["tool_choice"] == {
        "type": "none"
    }
    specific = openai_request_to_anthropic(
        {**base, "tool_choice": {"type": "function", "function": {"name": "f1"}}}
    )
    assert specific["tool_choice"] == {"type": "tool", "name": "f1"}


def test_temperature_top_p_max_tokens_passed_through() -> None:
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 1234,
    }
    out = openai_request_to_anthropic(req)
    assert out["temperature"] == 0.3
    assert out["top_p"] == 0.9
    assert out["max_tokens"] == 1234


def test_stop_sequences_translated() -> None:
    out1 = openai_request_to_anthropic(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "stop": "END",
        }
    )
    assert out1["stop_sequences"] == ["END"]

    out2 = openai_request_to_anthropic(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "stop": ["END", "STOP"],
        }
    )
    assert out2["stop_sequences"] == ["END", "STOP"]


def test_stream_flag_preserved() -> None:
    out = openai_request_to_anthropic(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }
    )
    assert out["stream"] is True


def test_image_block_passthrough() -> None:
    """Base64 image content blocks pass through as opaque content. The
    translator doesn't transcode; Anthropic and OpenAI both accept a
    list of content blocks on user messages, and we leave the
    detailed shape to the upstream provider to validate."""
    image_block = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
    }
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what's in this image?"},
                    image_block,
                ],
            }
        ],
    }
    out = openai_request_to_anthropic(req)
    # Content list preserved verbatim (not flattened, not dropped).
    assert out["messages"][0]["content"] == req["messages"][0]["content"]


def test_malformed_tool_call_arguments_recovered() -> None:
    """A tool call with non-JSON arguments shouldn't crash the
    translator; we wrap the raw string in {"_raw": ...} so the bug
    surfaces upstream rather than silently dropping the call."""
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "x",
                        "type": "function",
                        "function": {"name": "f", "arguments": "not json {"},
                    }
                ],
            }
        ],
    }
    out = openai_request_to_anthropic(req)
    assistant = out["messages"][0]
    tool_use = assistant["content"][0]
    assert tool_use["type"] == "tool_use"
    assert tool_use["input"] == {"_raw": "not json {"}


# ---------------------------------------------------------------------------
# Anthropic stream events → OpenAI SSE chunks
# ---------------------------------------------------------------------------


def _decode_sse(chunks: list[str]) -> list[Any]:
    """Decode a list of SSE chunk strings into a list of parsed
    payloads (with ``[DONE]`` represented as the literal string)."""
    out: list[Any] = []
    for c in chunks:
        assert c.startswith("data: "), c
        assert c.endswith("\n\n"), c
        payload = c.removeprefix("data: ").removesuffix("\n\n")
        if payload == "[DONE]":
            out.append("[DONE]")
        else:
            out.append(json.loads(payload))
    return out


def test_first_chunk_emits_role_assistant() -> None:
    chunks = _decode_sse(
        list(
            anthropic_stream_to_openai_chunks(
                iter([]),
                model="claude-sonnet-4-6",
                request_id="r1",
            )
        )
    )
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[-1] == "[DONE]"


def test_text_delta_emits_content_delta() -> None:
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    chunks = _decode_sse(
        list(
            anthropic_stream_to_openai_chunks(
                iter(events), model="claude-sonnet-4-6", request_id="r1"
            )
        )
    )
    # role chunk, content chunk, [DONE]
    assert chunks[1]["choices"][0]["delta"]["content"] == "Hello"
    assert chunks[-1] == "[DONE]"


def test_tool_use_start_emits_tool_call_with_id_and_name() -> None:
    events = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_abc",
                "name": "search",
                "input": {},
            },
        },
        {"type": "message_stop"},
    ]
    chunks = _decode_sse(
        list(
            anthropic_stream_to_openai_chunks(
                iter(events), model="claude-sonnet-4-6", request_id="r1"
            )
        )
    )
    tc = chunks[1]["choices"][0]["delta"]["tool_calls"][0]
    assert tc["index"] == 0
    assert tc["id"] == "toolu_abc"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "search"
    assert tc["function"]["arguments"] == ""


def test_input_json_delta_appended_to_tool_call_arguments() -> None:
    events = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "tu1", "name": "f"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"a":'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": " 1}"},
        },
        {"type": "message_stop"},
    ]
    chunks = _decode_sse(
        list(
            anthropic_stream_to_openai_chunks(
                iter(events), model="claude-sonnet-4-6", request_id="r1"
            )
        )
    )
    # role, tool_call_start, two partial-json chunks, [DONE]
    assert chunks[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == '{"a":'
    assert chunks[3]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == " 1}"


def test_message_delta_with_stop_reason_emits_finish_reason() -> None:
    events = [
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ]
    chunks = _decode_sse(
        list(
            anthropic_stream_to_openai_chunks(
                iter(events), model="claude-sonnet-4-6", request_id="r1"
            )
        )
    )
    assert chunks[1]["choices"][0]["finish_reason"] == "stop"


def test_message_stop_emits_done_marker() -> None:
    chunks = list(
        anthropic_stream_to_openai_chunks(
            iter([{"type": "message_stop"}]),
            model="claude-sonnet-4-6",
            request_id="r1",
        )
    )
    assert chunks[-1] == "data: [DONE]\n\n"


def test_max_tokens_stop_reason_maps_to_length() -> None:
    assert _translate_finish_reason("max_tokens") == "length"


def test_tool_use_stop_reason_maps_to_tool_calls() -> None:
    assert _translate_finish_reason("tool_use") == "tool_calls"


def test_stop_sequence_reason_maps_to_stop() -> None:
    assert _translate_finish_reason("stop_sequence") == "stop"


def test_unknown_stop_reason_defaults_to_stop() -> None:
    assert _translate_finish_reason("something_new") == "stop"


# ---------------------------------------------------------------------------
# Non-streaming response translation
# ---------------------------------------------------------------------------


def test_anthropic_response_text_only() -> None:
    resp = {
        "content": [{"type": "text", "text": "hi"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }
    out = anthropic_response_to_openai(resp, model="claude-sonnet-4-6", request_id="r1")
    assert out["choices"][0]["message"]["content"] == "hi"
    assert out["choices"][0]["finish_reason"] == "stop"
    assert out["usage"]["total_tokens"] == 13


def test_anthropic_response_with_tool_use() -> None:
    resp = {
        "content": [
            {"type": "text", "text": "I'll search"},
            {
                "type": "tool_use",
                "id": "tu1",
                "name": "search",
                "input": {"q": "foo"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    out = anthropic_response_to_openai(resp, model="claude-sonnet-4-6", request_id="r1")
    msg = out["choices"][0]["message"]
    assert msg["content"] == "I'll search"
    assert msg["tool_calls"][0]["id"] == "tu1"
    assert msg["tool_calls"][0]["function"]["name"] == "search"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"q": "foo"}
    assert out["choices"][0]["finish_reason"] == "tool_calls"
