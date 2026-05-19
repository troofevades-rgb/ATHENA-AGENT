"""Anthropic message-shape translation (Ollama format → content blocks)."""

from __future__ import annotations

from athena.providers.anthropic import AnthropicProvider


def test_user_message_passes_through() -> None:
    out = AnthropicProvider._translate_messages(
        [
            {"role": "user", "content": "hi"},
        ]
    )
    assert out == [{"role": "user", "content": "hi"}]


def test_assistant_with_text_only() -> None:
    out = AnthropicProvider._translate_messages(
        [
            {"role": "assistant", "content": "ok"},
        ]
    )
    assert out == [
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    ]


def test_assistant_with_tool_calls_emits_tool_use_blocks() -> None:
    out = AnthropicProvider._translate_messages(
        [
            {
                "role": "assistant",
                "content": "Reading.",
                "tool_calls": [
                    {
                        "id": "call_42",
                        "function": {
                            "name": "Read",
                            "arguments": {"file_path": "x.py"},
                        },
                    }
                ],
            },
        ]
    )
    assert out[0]["role"] == "assistant"
    blocks = out[0]["content"]
    assert blocks[0] == {"type": "text", "text": "Reading."}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "call_42",
        "name": "Read",
        "input": {"file_path": "x.py"},
    }


def test_tool_role_becomes_user_with_tool_result_blocks() -> None:
    out = AnthropicProvider._translate_messages(
        [
            {
                "role": "tool",
                "tool_call_id": "call_42",
                "name": "Read",
                "content": "file contents here",
            },
        ]
    )
    assert out[0]["role"] == "user"
    assert out[0]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call_42",
            "content": "file contents here",
        }
    ]


def test_consecutive_tool_results_collapse_into_one_user_message() -> None:
    out = AnthropicProvider._translate_messages(
        [
            {"role": "tool", "tool_call_id": "a", "content": "ra"},
            {"role": "tool", "tool_call_id": "b", "content": "rb"},
        ]
    )
    assert len(out) == 1
    assert out[0]["role"] == "user"
    assert len(out[0]["content"]) == 2


def test_missing_id_paired_between_call_and_result() -> None:
    """Both turns lack ids — translation must synthesize matching ids."""
    out = AnthropicProvider._translate_messages(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {"name": "Read", "arguments": {"file_path": "x"}},
                    }
                ],
            },
            {"role": "tool", "name": "Read", "content": "x contents"},
        ]
    )
    assistant_blocks = out[0]["content"]
    tool_use = next(b for b in assistant_blocks if b["type"] == "tool_use")
    user_blocks = out[1]["content"]
    tool_result = user_blocks[0]
    assert tool_use["id"] == tool_result["tool_use_id"]


def test_json_string_arguments_are_parsed() -> None:
    out = AnthropicProvider._translate_messages(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "Read",
                            "arguments": '{"file_path": "x.py"}',
                        },
                    }
                ],
            },
        ]
    )
    tool_use = out[0]["content"][0]
    assert tool_use["input"] == {"file_path": "x.py"}


def test_assistant_with_no_content_or_tool_calls_is_dropped() -> None:
    """Anthropic rejects assistant turns with empty content arrays AND
    rejects text blocks with empty strings — the safest move is to
    drop the turn so nothing about the message log enrages the API."""
    out = AnthropicProvider._translate_messages(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
        ]
    )
    # Only the user turn survives.
    assert len(out) == 1
    assert out[0]["role"] == "user"


def test_assistant_pre_built_blocks_strip_empty_text() -> None:
    """Upstream code that already emitted assistant content as block
    list may include placeholder empty-text blocks (mid-stream
    interrupts, plugin elision). Filter those out instead of
    forwarding them straight into the API where they 400."""
    out = AnthropicProvider._translate_messages(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "text", "text": "  "},
                    {"type": "text", "text": "real content"},
                ],
            },
        ]
    )
    blocks = out[0]["content"]
    assert blocks == [{"type": "text", "text": "real content"}]


def test_assistant_only_tool_use_no_text_passes_through() -> None:
    """Normal case: the model emits a tool call with no preamble. The
    assistant turn carries only a tool_use block; Anthropic accepts
    this, the translator must not invent a placeholder text block
    that would cause a 400."""
    out = AnthropicProvider._translate_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {"name": "Read", "arguments": {"file_path": "x.py"}},
                    }
                ],
            },
        ]
    )
    blocks = out[0]["content"]
    # Exactly one block, exactly the tool_use — no empty text smuggled in.
    assert len(blocks) == 1
    assert blocks[0]["type"] == "tool_use"
