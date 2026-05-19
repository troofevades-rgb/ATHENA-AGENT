"""Legacy OpenAI function_call format (gpt-3.5*, gpt-4-0613)."""

from __future__ import annotations

from athena.providers.parsers.openai_function import parse


def test_legacy_function_call_format():
    raw = {
        "message": {
            "function_call": {
                "name": "Read",
                "arguments": '{"file_path": "/etc/hostname"}',
            }
        }
    }
    cleaned, calls = parse("I'll do that.", raw)
    assert cleaned == "I'll do that."  # content unchanged
    assert len(calls) == 1
    assert calls[0]["name"] == "Read"
    assert calls[0]["arguments"] == {"file_path": "/etc/hostname"}


def test_arguments_string_parsed_to_dict():
    """OpenAI always sends arguments as a JSON string; the parser must
    deserialize it before returning."""
    raw = {
        "message": {
            "function_call": {
                "name": "Bash",
                "arguments": '{"command": "ls -la"}',
            }
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {"command": "ls -la"}
    assert isinstance(calls[0]["arguments"], dict)


def test_arguments_dict_passed_through():
    """A compat server might already have parsed the JSON; dict in →
    dict out, unchanged."""
    raw = {
        "message": {
            "function_call": {
                "name": "X",
                "arguments": {"k": "v"},
            }
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {"k": "v"}


def test_malformed_arguments_string_wrapped():
    raw = {
        "message": {
            "function_call": {
                "name": "X",
                "arguments": "not-json",
            }
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {"_raw": "not-json"}


def test_empty_arguments_string_treated_as_empty_dict():
    raw = {"message": {"function_call": {"name": "X", "arguments": ""}}}
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {}


def test_no_message_falls_through():
    cleaned, calls = parse("hi", {})
    assert cleaned == "hi"
    assert calls == []


def test_no_function_call_falls_through():
    """message present but no function_call field."""
    cleaned, calls = parse("hi", {"message": {"content": "hi"}})
    assert calls == []


def test_function_call_without_name_skipped():
    raw = {"message": {"function_call": {"arguments": "{}"}}}
    _, calls = parse("", raw)
    assert calls == []
