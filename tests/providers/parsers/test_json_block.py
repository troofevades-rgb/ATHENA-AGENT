"""Bare-JSON content recovery (last-resort parser)."""

from __future__ import annotations

from athena.providers.parsers.json_block import parse


def test_bare_json_object_as_whole_response():
    """The only case json_block recovers: the ENTIRE response is a JSON
    object with a name field. Conservative on purpose."""
    content = '{"name": "Read", "arguments": {"file_path": "/etc/hostname"}}'
    cleaned, calls = parse(content, {})
    assert cleaned == ""
    assert calls[0]["name"] == "Read"
    assert calls[0]["arguments"] == {"file_path": "/etc/hostname"}


def test_whitespace_around_json_tolerated():
    content = '  \n  {"name": "X", "arguments": {"k": 1}}  \n  '
    _, calls = parse(content, {})
    assert calls[0]["name"] == "X"


def test_embedded_json_in_prose_NOT_recovered():
    """Conservative: a JSON object inside surrounding prose is NOT
    treated as a tool call — would mangle legitimate documentation."""
    content = 'Look at this example: {"name": "X", "arguments": {}} — that\'s how tool calls work.'
    cleaned, calls = parse(content, {})
    assert calls == []
    assert cleaned == content  # passed through unchanged


def test_json_without_name_field_passed_through():
    """A JSON object with no 'name' is not a tool call. Even when the
    whole response is JSON, conservative semantics apply."""
    content = '{"file_path": "/x", "operation": "read"}'
    cleaned, calls = parse(content, {})
    assert calls == []
    assert cleaned == content


def test_non_dict_json_passed_through():
    """JSON array, number, string, bool — none of these are tool calls."""
    for content in ("[1, 2, 3]", "42", '"hello"', "true", "null"):
        cleaned, calls = parse(content, {})
        assert calls == [], f"falsely matched: {content!r}"


def test_arguments_as_json_string_parsed():
    content = '{"name": "X", "arguments": "{\\"k\\": \\"v\\"}"}'
    _, calls = parse(content, {})
    assert calls[0]["arguments"] == {"k": "v"}


def test_arguments_missing_treated_as_empty_dict():
    content = '{"name": "NoArgs"}'
    _, calls = parse(content, {})
    assert calls[0]["arguments"] == {}


def test_malformed_json_passes_content_through():
    content = '{"name": "Read", "arguments": {oops bad}}'
    cleaned, calls = parse(content, {})
    assert calls == []
    assert cleaned == content


def test_parser_never_raises_on_garbage():
    parse("", {})
    parse("not json at all", {})
    parse("{", {})
    parse(None, {})  # type: ignore[arg-type]
