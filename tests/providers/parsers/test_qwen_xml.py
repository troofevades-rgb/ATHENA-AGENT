"""Qwen XML-leakage parser — <tool_call>{...}</tool_call> recovery."""

from __future__ import annotations

from athena.providers.parsers.qwen_xml_leakage import parse


def test_single_tool_call_extracted():
    content = '<tool_call>{"name": "Read", "arguments": {"file_path": "/etc/hostname"}}</tool_call>'
    cleaned, calls = parse(content, {})
    assert cleaned == ""
    assert calls == [{"name": "Read", "arguments": {"file_path": "/etc/hostname"}, "id": ""}]


def test_multiple_tool_calls_in_order():
    content = (
        '<tool_call>{"name": "A", "arguments": {"k": 1}}</tool_call>'
        '<tool_call>{"name": "B", "arguments": {"k": 2}}</tool_call>'
    )
    _, calls = parse(content, {})
    assert [c["name"] for c in calls] == ["A", "B"]


def test_content_preserved_around_tool_calls():
    """The model's natural-language preamble before / after the tool call
    must be preserved in cleaned_content (and stripped of the tool_call
    block itself)."""
    content = (
        "I'll read that file. "
        '<tool_call>{"name": "Read", "arguments": {"path": "/x"}}</tool_call>'
        " Then I'll process it."
    )
    cleaned, calls = parse(content, {})
    assert "I'll read that file." in cleaned
    assert "Then I'll process it." in cleaned
    assert "<tool_call>" not in cleaned
    assert calls[0]["name"] == "Read"


def test_malformed_json_leaves_block_in_content():
    """If the JSON inside the tags doesn't parse, keep the original block
    so the model can see what it emitted next turn."""
    content = '<tool_call>{"name": "X", "arguments": {bad json}}</tool_call>'
    cleaned, calls = parse(content, {})
    assert calls == []
    assert "<tool_call>" in cleaned


def test_native_tool_calls_preferred_when_present():
    """Some Ollama versions actually parse Qwen's leak server-side and
    populate raw_response.message.tool_calls. Trust that path."""
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "FromNative", "arguments": {"k": "v"}}},
            ]
        }
    }
    content = '<tool_call>{"name": "FromContent", "arguments": {}}</tool_call>'
    cleaned, calls = parse(content, raw)
    assert calls[0]["name"] == "FromNative"
    # Content is returned unchanged when native won.
    assert "<tool_call>" in cleaned


def test_string_arguments_parsed_to_dict():
    """Some Qwen-coder variants emit arguments as a JSON string inside
    the JSON. Deserialize."""
    content = '<tool_call>{"name": "X", "arguments": "{\\"k\\": \\"v\\"}"}</tool_call>'
    _, calls = parse(content, {})
    assert calls[0]["arguments"] == {"k": "v"}


def test_tool_call_without_name_keeps_block():
    """A tool_call without a name isn't a tool call; preserve the block."""
    content = '<tool_call>{"arguments": {"x": 1}}</tool_call>'
    cleaned, calls = parse(content, {})
    assert calls == []
    assert "<tool_call>" in cleaned


def test_no_tool_call_tags_returns_content_unchanged():
    cleaned, calls = parse("plain prose, no tool call here", {})
    assert cleaned == "plain prose, no tool call here"
    assert calls == []


def test_parser_never_raises_on_garbage():
    parse("", {})
    parse("<tool_call><tool_call>", {})
    parse("<tool_call>{not even close to json", {})
    parse(None, {})  # type: ignore[arg-type]
