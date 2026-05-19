"""Current OpenAI tool_calls array format."""

from __future__ import annotations

from athena.providers.parsers.openai_tools import parse


def test_tools_array_format():
    raw = {
        "message": {
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "Read", "arguments": '{"path": "/tmp/x"}'},
                },
            ]
        }
    }
    cleaned, calls = parse("ok", raw)
    assert cleaned == "ok"
    assert len(calls) == 1
    assert calls[0]["name"] == "Read"
    assert calls[0]["arguments"] == {"path": "/tmp/x"}
    assert calls[0]["id"] == "call_abc"


def test_multiple_tool_calls_in_order():
    raw = {
        "message": {
            "tool_calls": [
                {"id": "c1", "function": {"name": "Read", "arguments": '{"p": 1}'}},
                {"id": "c2", "function": {"name": "Write", "arguments": '{"p": 2}'}},
                {"id": "c3", "function": {"name": "Edit", "arguments": '{"p": 3}'}},
            ]
        }
    }
    _, calls = parse("", raw)
    names = [c["name"] for c in calls]
    assert names == ["Read", "Write", "Edit"]


def test_arguments_already_dict_passed_through():
    """Some OpenAI-compatible servers parse arguments before returning;
    accept both shapes."""
    raw = {
        "message": {
            "tool_calls": [
                {"id": "c1", "function": {"name": "X", "arguments": {"k": "v"}}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls[0]["arguments"] == {"k": "v"}


def test_malformed_arguments_wrapped_not_raised():
    raw = {
        "message": {
            "tool_calls": [
                {"id": "c1", "function": {"name": "X", "arguments": "not-json{"}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert "_raw" in calls[0]["arguments"]


def test_tool_call_without_function_skipped():
    raw = {
        "message": {
            "tool_calls": [
                {"id": "missing"},  # no function key
                {"id": "real", "function": {"name": "X", "arguments": "{}"}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert len(calls) == 1
    assert calls[0]["id"] == "real"


def test_missing_name_skipped():
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"arguments": "{}"}},
            ]
        }
    }
    _, calls = parse("", raw)
    assert calls == []


def test_no_tool_calls_array_falls_through():
    cleaned, calls = parse("plain", {"message": {"content": "plain"}})
    assert cleaned == "plain"
    assert calls == []


def test_handles_missing_message():
    cleaned, calls = parse("hi", {})
    assert cleaned == "hi"
    assert calls == []
