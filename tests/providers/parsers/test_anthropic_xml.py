"""Anthropic content-block parser."""

from __future__ import annotations

from athena.providers.parsers.anthropic_xml import parse


def test_tool_use_block_extracted():
    raw = {
        "content": [
            {"type": "text", "text": "I'll read that file."},
            {
                "type": "tool_use",
                "id": "tu_01abc",
                "name": "Read",
                "input": {"file_path": "/etc/hostname"},
            },
        ]
    }
    cleaned, calls = parse("", raw)
    assert cleaned == "I'll read that file."
    assert len(calls) == 1
    assert calls[0]["name"] == "Read"
    assert calls[0]["arguments"] == {"file_path": "/etc/hostname"}
    assert calls[0]["id"] == "tu_01abc"


def test_multiple_tool_use_blocks_in_doc_order():
    raw = {
        "content": [
            {"type": "text", "text": "Reading both files. "},
            {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"path": "a"}},
            {"type": "tool_use", "id": "tu_2", "name": "Read", "input": {"path": "b"}},
        ]
    }
    cleaned, calls = parse("", raw)
    assert cleaned == "Reading both files."
    assert [c["arguments"]["path"] for c in calls] == ["a", "b"]


def test_text_block_preserved_around_tool_uses():
    raw = {
        "content": [
            {"type": "text", "text": "First "},
            {"type": "tool_use", "id": "x", "name": "X", "input": {}},
            {"type": "text", "text": "then second."},
        ]
    }
    cleaned, calls = parse("", raw)
    assert cleaned == "First then second."
    assert len(calls) == 1


def test_no_content_array_falls_through():
    """Streaming responses don't carry the content array — parser must
    return (content, []) without crashing."""
    cleaned, calls = parse("streamed text", {})
    assert cleaned == "streamed text"
    assert calls == []


def test_non_dict_input_block_skipped():
    """Defensive against weird API responses — non-dict entries don't crash."""
    raw = {
        "content": [
            "garbage",
            {"type": "text", "text": "real"},
            None,
        ]
    }
    cleaned, calls = parse("", raw)
    assert cleaned == "real"


def test_tool_use_without_name_skipped():
    raw = {
        "content": [
            {"type": "tool_use", "id": "x", "input": {"a": 1}},  # no name
            {"type": "tool_use", "id": "y", "name": "Real", "input": {"b": 2}},
        ]
    }
    _, calls = parse("", raw)
    assert len(calls) == 1
    assert calls[0]["name"] == "Real"


def test_tool_use_with_non_dict_input_coerced():
    """input is supposed to be a dict; if not, wrap it."""
    raw = {
        "content": [
            {"type": "tool_use", "id": "x", "name": "Tool", "input": "not-a-dict"},
        ]
    }
    _, calls = parse("", raw)
    assert "_raw" in calls[0]["arguments"]


def test_parser_never_raises_on_garbage():
    """Sanity — feed random shapes, no exceptions."""
    parse("", None)  # type: ignore[arg-type]
    parse("", {"content": "not a list"})
    parse("", {"content": [{}, {}, {}]})
