"""Tests for athena.proxy.translate (T3-01R.2).

The six named cases from the spec:

  test_content_chunks_to_sse_deltas
  test_tool_call_chunk_to_openai_tool_calls
  test_end_maps_finish_reason
  test_usage_passthrough
  test_nonstreaming_collects_to_one_object
  test_done_sentinel_emitted

Plus a handful of edge-case assertions that previously lived in
test_server.py against the pre-retarget FastAPI implementation —
moving them here puts the translation logic under test in
isolation.
"""

from __future__ import annotations

import json

from athena.providers.base import StreamChunk
from athena.proxy.translate import (
    collect_chunks_to_openai_response,
    stream_chunks_to_openai_sse,
)


def _decode(chunks: list[str]) -> list:
    out = []
    for line in chunks:
        assert line.startswith("data: "), line
        assert line.endswith("\n\n"), line
        body = line.removeprefix("data: ").removesuffix("\n\n")
        out.append("[DONE]" if body == "[DONE]" else json.loads(body))
    return out


def test_content_chunks_to_sse_deltas() -> None:
    iters = [
        StreamChunk(kind="content", payload="Hel"),
        StreamChunk(kind="content", payload="lo"),
        StreamChunk(kind="end", payload={"reason": "stop"}),
    ]
    out = _decode(
        list(stream_chunks_to_openai_sse(iter(iters), model="claude-sonnet-4-6", request_id="r1"))
    )
    # role chunk, two content deltas, finish chunk, [DONE]
    contents = [
        c["choices"][0]["delta"].get("content")
        for c in out
        if c != "[DONE]" and c["choices"][0]["delta"].get("content") is not None
    ]
    assert contents == ["Hel", "lo"]


def test_tool_call_chunk_to_openai_tool_calls() -> None:
    chunks = [
        StreamChunk(
            kind="tool_call",
            payload={
                "id": "toolu_42",
                "name": "search",
                "arguments": '{"q":"foo"}',
            },
        ),
        StreamChunk(kind="end", payload={"reason": "tool_use"}),
    ]
    out = _decode(list(stream_chunks_to_openai_sse(iter(chunks), model="m", request_id="r1")))
    tool_chunks = [c for c in out if c != "[DONE]" and c["choices"][0]["delta"].get("tool_calls")]
    assert len(tool_chunks) == 1
    tc = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
    assert tc["id"] == "toolu_42"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "search"
    assert tc["function"]["arguments"] == '{"q":"foo"}'
    # Multiple tool_calls in the same stream get sequential indices.
    chunks2 = [
        StreamChunk(kind="tool_call", payload={"id": "a", "name": "f1"}),
        StreamChunk(kind="tool_call", payload={"id": "b", "name": "f2"}),
        StreamChunk(kind="end", payload={"reason": "tool_use"}),
    ]
    out2 = _decode(list(stream_chunks_to_openai_sse(iter(chunks2), model="m", request_id="r")))
    indices = [
        c["choices"][0]["delta"]["tool_calls"][0]["index"]
        for c in out2
        if c != "[DONE]" and c["choices"][0]["delta"].get("tool_calls")
    ]
    assert indices == [0, 1]


def test_end_maps_finish_reason() -> None:
    cases = {
        "stop": "stop",
        "end_turn": "stop",
        "length": "length",
        "max_tokens": "length",
        "tool_calls": "tool_calls",
        "tool_use": "tool_calls",
        "stop_sequence": "stop",
        "something_unknown": "stop",  # default fallback
    }
    for raw, expected in cases.items():
        out = _decode(
            list(
                stream_chunks_to_openai_sse(
                    iter([StreamChunk(kind="end", payload={"reason": raw})]),
                    model="m",
                    request_id="r",
                )
            )
        )
        finish_chunks = [c for c in out if c != "[DONE]" and c["choices"][0].get("finish_reason")]
        assert finish_chunks[-1]["choices"][0]["finish_reason"] == expected, raw


def test_usage_passthrough() -> None:
    seen: list[tuple[int, int, int]] = []

    chunks = [
        StreamChunk(kind="content", payload="hi"),
        StreamChunk(
            kind="usage",
            payload={
                "prompt_tokens": 5,
                "completion_tokens": 2,
                "cache_read_input_tokens": 4,
            },
        ),
        StreamChunk(kind="end", payload={"reason": "stop"}),
    ]
    list(
        stream_chunks_to_openai_sse(
            iter(chunks),
            model="m",
            request_id="r",
            on_usage=lambda i, o, c: seen.append((i, o, c)),
        )
    )
    assert seen == [(5, 2, 4)]


def test_nonstreaming_collects_to_one_object() -> None:
    chunks = [
        StreamChunk(kind="content", payload="Hello "),
        StreamChunk(kind="content", payload="world."),
        StreamChunk(
            kind="usage",
            payload={"prompt_tokens": 10, "completion_tokens": 3},
        ),
        StreamChunk(kind="end", payload={"reason": "stop"}),
    ]
    obj = collect_chunks_to_openai_response(iter(chunks), model="m", request_id="rx")
    assert obj["object"] == "chat.completion"
    assert obj["id"] == "rx"
    assert obj["model"] == "m"
    assert obj["choices"][0]["message"]["content"] == "Hello world."
    assert obj["choices"][0]["finish_reason"] == "stop"
    assert obj["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
    }


def test_nonstreaming_collects_tool_calls() -> None:
    chunks = [
        StreamChunk(
            kind="tool_call",
            payload={"id": "t1", "name": "search", "arguments": '{"q":"x"}'},
        ),
        StreamChunk(kind="end", payload={"reason": "tool_use"}),
    ]
    obj = collect_chunks_to_openai_response(iter(chunks), model="m", request_id="rx")
    msg = obj["choices"][0]["message"]
    assert msg["content"] is None
    assert msg["tool_calls"][0]["id"] == "t1"
    assert msg["tool_calls"][0]["function"]["name"] == "search"
    assert obj["choices"][0]["finish_reason"] == "tool_calls"


def test_done_sentinel_emitted() -> None:
    """[DONE] is the last frame even if the upstream stream is
    empty."""
    out = list(stream_chunks_to_openai_sse(iter([]), model="m", request_id="r"))
    assert out[-1] == "data: [DONE]\n\n"

    # Same for streams that end without an explicit 'end' chunk —
    # we synthesize a finish_reason then DONE.
    out2 = list(
        stream_chunks_to_openai_sse(
            iter([StreamChunk(kind="content", payload="x")]),
            model="m",
            request_id="r",
        )
    )
    assert out2[-1] == "data: [DONE]\n\n"
    decoded = _decode(out2)
    finish = [c for c in decoded if c != "[DONE]" and c["choices"][0].get("finish_reason")]
    assert finish[-1]["choices"][0]["finish_reason"] == "stop"


def test_first_chunk_emits_role_assistant() -> None:
    """OpenAI clients expect ``role=assistant`` on the opening
    delta; we send it unconditionally."""
    out = _decode(list(stream_chunks_to_openai_sse(iter([]), model="m", request_id="r")))
    assert out[0]["choices"][0]["delta"]["role"] == "assistant"


def test_tool_call_with_dict_arguments_json_encoded() -> None:
    """A provider that emits arguments as a dict (instead of a
    JSON-encoded string) still gets a string arguments field on the
    wire — that's what OpenAI clients expect."""
    chunks = [
        StreamChunk(
            kind="tool_call",
            payload={"id": "t1", "name": "f", "arguments": {"x": 1}},
        ),
        StreamChunk(kind="end", payload={"reason": "tool_use"}),
    ]
    out = _decode(list(stream_chunks_to_openai_sse(iter(chunks), model="m", request_id="r")))
    tool_chunks = [c for c in out if c != "[DONE]" and c["choices"][0]["delta"].get("tool_calls")]
    args = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
    assert args == '{"x": 1}'
