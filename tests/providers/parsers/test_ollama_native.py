"""Ollama native tool_calls — same shape as OpenAI tools."""

from __future__ import annotations

from athena.providers.parsers import resolve_parser
from athena.providers.parsers.ollama_native import parse


def test_native_format_passthrough():
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "Read", "arguments": {"file_path": "/etc/hostname"}}},
            ]
        }
    }
    cleaned, calls = parse("ok", raw)
    assert cleaned == "ok"
    assert calls == [
        {"name": "Read", "arguments": {"file_path": "/etc/hostname"}, "id": ""},
    ]


def test_native_with_id_preserved():
    """Ollama sometimes assigns IDs; pass them through when present."""
    raw = {
        "message": {
            "tool_calls": [
                {
                    "id": "ollama-call-1",
                    "function": {"name": "Bash", "arguments": {"command": "ls"}},
                },
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["id"] == "ollama-call-1"


def test_string_arguments_parsed():
    """Some Ollama versions emit arguments as a JSON string."""
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "X", "arguments": '{"k": "v"}'}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {"k": "v"}


def test_registered_as_provider_default_for_ollama():
    """resolve_parser('ollama', '<any-model-without-a-narrower-glob>')
    should return ollama_native's parse function — it's the default."""
    parser = resolve_parser("ollama", "some-random-non-qwen-model")
    # Verify it's actually the ollama_native parser by feeding native data.
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "X", "arguments": {"a": 1}}},
            ]
        }
    }
    _, calls = parser("", raw)
    assert calls[0]["name"] == "X"


def test_no_tool_calls_falls_through():
    cleaned, calls = parse("plain text", {"message": {"content": "plain text"}})
    assert cleaned == "plain text"
    assert calls == []


def test_handles_garbage_input():
    """Defensive: non-dict raw_response, missing message, etc."""
    assert parse("", None)[1] == []  # type: ignore[arg-type]
    assert parse("", {"message": "not a dict"})[1] == []
    assert parse("", {"message": {"tool_calls": "not a list"}})[1] == []


def test_skips_non_dict_tool_call_entries():
    """tc not a dict → skip (line 36)."""
    raw = {
        "message": {
            "tool_calls": ["garbage", None, 42, {"function": {"name": "Real", "arguments": {}}}]
        }
    }
    _, calls = parse("", raw)
    assert len(calls) == 1
    assert calls[0]["name"] == "Real"


def test_skips_entry_with_non_dict_function():
    """tc.function not a dict → skip (line 39)."""
    raw = {
        "message": {
            "tool_calls": [
                {"function": "not a dict"},
                {"function": None},
                {"function": {"name": "Real", "arguments": {}}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert len(calls) == 1
    assert calls[0]["name"] == "Real"


def test_skips_entry_with_missing_or_nonstring_name():
    """name absent / empty / non-string → skip (line 42)."""
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"arguments": {}}},
                {"function": {"name": "", "arguments": {}}},
                {"function": {"name": 42, "arguments": {}}},
                {"function": {"name": "Real", "arguments": {}}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert len(calls) == 1


def test_string_arguments_malformed_json_falls_back_to_raw():
    """JSONDecodeError → wrap as _raw (line 51)."""
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "X", "arguments": "{not valid json"}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {"_raw": "{not valid json"}


def test_string_arguments_parsed_to_non_dict_falls_back_to_raw():
    """JSON parses but isn't a dict (array) → wrap as _raw (line 49)."""
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "X", "arguments": "[1,2,3]"}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {"_raw": "[1,2,3]"}


def test_empty_string_arguments_becomes_empty_dict():
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "X", "arguments": "   "}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {}


def test_non_string_non_dict_arguments_becomes_empty_dict():
    """arguments is e.g. an int or None → fall through to {} (line 53)."""
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "X", "arguments": 42}},
                {"function": {"name": "Y", "arguments": None}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {}
    assert calls[1]["arguments"] == {}


def test_non_string_id_becomes_empty_string():
    raw = {
        "message": {
            "tool_calls": [
                {"id": 99, "function": {"name": "X", "arguments": {}}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["id"] == ""
