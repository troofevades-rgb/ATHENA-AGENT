"""Code-fenced JSON tool-call recovery."""
from __future__ import annotations

from athena.providers.parsers.code_fenced_json import parse


def test_json_fence_with_name_and_arguments():
    content = (
        "Here's what I'll do:\n"
        "```json\n"
        '{"name": "Read", "arguments": {"file_path": "/etc/hostname"}}\n'
        "```\n"
        "After that, I'll process it."
    )
    cleaned, calls = parse(content, {})
    assert len(calls) == 1
    assert calls[0]["name"] == "Read"
    assert calls[0]["arguments"] == {"file_path": "/etc/hostname"}
    assert "```json" not in cleaned
    assert "Here's what I'll do:" in cleaned
    assert "After that, I'll process it." in cleaned


def test_tool_call_fence_label_also_recognized():
    """Some models use ```tool_call instead of ```json."""
    content = (
        "```tool_call\n"
        '{"name": "Write", "arguments": {"path": "x"}}\n'
        "```"
    )
    _, calls = parse(content, {})
    assert calls[0]["name"] == "Write"


def test_plain_code_fence_left_alone():
    """A regular Python code block must NOT be mistaken for a tool call."""
    content = (
        "```python\n"
        "def hello():\n"
        "    print('hi')\n"
        "```"
    )
    cleaned, calls = parse(content, {})
    assert calls == []
    assert "def hello()" in cleaned


def test_fence_with_unparsable_json_left_alone():
    content = (
        "```json\n"
        '{not valid json}\n'
        "```"
    )
    cleaned, calls = parse(content, {})
    assert calls == []
    assert "{not valid json}" in cleaned


def test_fence_missing_name_field_left_alone():
    """A JSON object without a 'name' key isn't a tool call."""
    content = (
        "```json\n"
        '{"file_path": "/x"}\n'
        "```"
    )
    cleaned, calls = parse(content, {})
    assert calls == []
    assert '"file_path"' in cleaned


def test_arguments_as_json_string_parsed():
    """Models occasionally double-encode arguments as a JSON string."""
    content = (
        "```json\n"
        '{"name": "X", "arguments": "{\\"k\\": \\"v\\"}"}\n'
        "```"
    )
    _, calls = parse(content, {})
    assert calls[0]["arguments"] == {"k": "v"}


def test_multiple_fences_extracted_in_order():
    content = (
        "First call:\n"
        "```json\n"
        '{"name": "A", "arguments": {}}\n'
        "```\n"
        "Second call:\n"
        "```json\n"
        '{"name": "B", "arguments": {}}\n'
        "```"
    )
    _, calls = parse(content, {})
    assert [c["name"] for c in calls] == ["A", "B"]


def test_no_fences_returns_content_unchanged():
    cleaned, calls = parse("no fences here", {})
    assert cleaned == "no fences here"
    assert calls == []


def test_parser_never_raises_on_garbage():
    parse("", {})
    parse("```json\n", {})
    parse("```", {})
    parse(None, {})  # type: ignore[arg-type]
