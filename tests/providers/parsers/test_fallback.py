"""fallback_parser — last-resort tool-call extractor.

Drives every branch of ``_native_tool_calls`` and ``_coerce_arguments``
so coverage on fallback.py stays at the prompt's 95% bar.
"""

from __future__ import annotations

from athena.providers.parsers.fallback import (
    _coerce_arguments,
    _native_tool_calls,
    fallback_parser,
)

# ---- _coerce_arguments --------------------------------------------------


def test_coerce_dict_passthrough():
    assert _coerce_arguments({"a": 1}) == {"a": 1}


def test_coerce_json_string_parses_to_dict():
    assert _coerce_arguments('{"a": 1}') == {"a": 1}


def test_coerce_empty_string_returns_empty_dict():
    assert _coerce_arguments("") == {}
    assert _coerce_arguments("   ") == {}


def test_coerce_malformed_json_string_wraps_raw():
    assert _coerce_arguments("not json") == {"_raw": "not json"}


def test_coerce_json_non_dict_wraps_raw():
    """A JSON value that's not a dict (e.g. an array) gets wrapped."""
    assert _coerce_arguments("[1, 2, 3]") == {"_raw": "[1, 2, 3]"}


def test_coerce_none_returns_empty_dict():
    assert _coerce_arguments(None) == {}


def test_coerce_int_returns_empty_dict():
    assert _coerce_arguments(42) == {}


# ---- _native_tool_calls -------------------------------------------------


def test_native_non_dict_input_returns_empty():
    assert _native_tool_calls(None) == []  # type: ignore[arg-type]
    assert _native_tool_calls("string") == []  # type: ignore[arg-type]


def test_native_top_level_tool_calls_with_function_shape():
    raw = {
        "tool_calls": [
            {"id": "abc", "function": {"name": "Read", "arguments": '{"p": 1}'}},
        ]
    }
    out = _native_tool_calls(raw)
    assert out == [{"name": "Read", "arguments": {"p": 1}, "id": "abc"}]


def test_native_top_level_tool_calls_with_flat_shape():
    raw = {
        "tool_calls": [
            {"name": "Read", "arguments": {"p": 1}, "id": "xyz"},
        ]
    }
    out = _native_tool_calls(raw)
    assert out == [{"name": "Read", "arguments": {"p": 1}, "id": "xyz"}]


def test_native_message_nested_tool_calls():
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "Bash", "arguments": "{}"}},
            ]
        }
    }
    out = _native_tool_calls(raw)
    assert out[0]["name"] == "Bash"


def test_native_skips_non_dict_entries():
    raw = {"tool_calls": ["garbage", None, 42, {"name": "Real", "arguments": {}}]}
    out = _native_tool_calls(raw)
    assert len(out) == 1
    assert out[0]["name"] == "Real"


def test_native_skips_entry_without_name():
    raw = {
        "tool_calls": [
            {"arguments": {"a": 1}},
            {"name": "Real", "arguments": {}},
        ]
    }
    out = _native_tool_calls(raw)
    assert len(out) == 1


def test_native_skips_entry_with_non_string_name():
    raw = {
        "tool_calls": [
            {"name": 42, "arguments": {}},
            {"name": "Real", "arguments": {}},
        ]
    }
    out = _native_tool_calls(raw)
    assert len(out) == 1


def test_native_id_coerced_to_empty_string_when_missing_or_nonstring():
    raw = {
        "tool_calls": [
            {"name": "A", "arguments": {}},  # no id
            {"name": "B", "arguments": {}, "id": 42},  # non-string id
        ]
    }
    out = _native_tool_calls(raw)
    assert out[0]["id"] == ""
    assert out[1]["id"] == ""


def test_native_message_not_a_dict_returns_empty():
    """raw["message"] exists but is the wrong shape."""
    assert _native_tool_calls({"message": "string"}) == []


def test_native_message_tool_calls_not_a_list_returns_empty():
    assert _native_tool_calls({"message": {"tool_calls": "not a list"}}) == []


# ---- fallback_parser ----------------------------------------------------


def test_fallback_passes_content_through_when_no_native():
    cleaned, calls = fallback_parser("hello world", {})
    assert cleaned == "hello world"
    assert calls == []


def test_fallback_returns_native_when_present():
    raw = {
        "message": {
            "tool_calls": [
                {"function": {"name": "X", "arguments": {}}},
            ]
        }
    }
    _, calls = fallback_parser("ignored", raw)
    assert calls[0]["name"] == "X"


def test_fallback_swallows_extractor_exception():
    """Even if _native_tool_calls somehow raised, fallback_parser must
    return (content, []) — not propagate. Use a dict subclass whose
    .get raises to simulate."""

    class _BadDict(dict):
        def get(self, key, default=None):
            raise RuntimeError("simulated failure")

    cleaned, calls = fallback_parser("kept", _BadDict())
    assert cleaned == "kept"
    assert calls == []
