"""Tests for athena.providers.schema_sanitizer (T2-05.2)."""

from __future__ import annotations

import json

from athena.providers.schema_sanitizer import sanitize_tool_call_args

# ---------------------------------------------------------------------------
# Already-valid JSON passes through unchanged
# ---------------------------------------------------------------------------


def test_already_valid_unchanged() -> None:
    raw = '{"foo": 1, "bar": "baz"}'
    result, fixes = sanitize_tool_call_args(raw)
    assert result == raw
    assert fixes == []


def test_already_valid_empty_object() -> None:
    result, fixes = sanitize_tool_call_args("{}")
    assert result == "{}"
    assert fixes == []


def test_already_valid_array() -> None:
    result, fixes = sanitize_tool_call_args('["a","b","c"]')
    assert result == '["a","b","c"]'
    assert fixes == []


def test_already_valid_with_apostrophe_in_string() -> None:
    """Strings containing apostrophes pass through; no single-quote
    pass should fire because double-quoted content already exists."""
    raw = '{"name": "Mike\'s file"}'
    result, fixes = sanitize_tool_call_args(raw)
    assert result == raw
    assert fixes == []


# ---------------------------------------------------------------------------
# Empty / garbage input
# ---------------------------------------------------------------------------


def test_empty_input_returns_none() -> None:
    result, _ = sanitize_tool_call_args("")
    assert result is None


def test_whitespace_only_returns_none() -> None:
    result, _ = sanitize_tool_call_args("   \n  \t ")
    assert result is None


# ---------------------------------------------------------------------------
# Smart quotes
# ---------------------------------------------------------------------------


def test_smart_double_quotes_recovered() -> None:
    raw = "{“key”: 1}"  # curly double-quotes around the key
    result, fixes = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"key": 1}
    assert any("smart quotes" in f for f in fixes)


def test_smart_single_quotes_recovered() -> None:
    """After smart-single -> ASCII single, the next pass converts
    single quotes to double quotes."""
    raw = "{‘key’: 1}"
    result, fixes = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"key": 1}


# ---------------------------------------------------------------------------
# Single quotes
# ---------------------------------------------------------------------------


def test_single_quoted_strings_converted() -> None:
    raw = "{'foo': 'bar'}"
    result, fixes = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"foo": "bar"}
    assert any("single quotes" in f for f in fixes)


def test_mixed_single_and_double_quotes_not_touched() -> None:
    """When the payload already has double-quoted strings, the
    single-quote pass should NOT fire (could break legitimate
    apostrophes inside double-quoted strings)."""
    raw = '{"name": "Mike\'s file", "tag": \'broken\'}'
    result, _ = sanitize_tool_call_args(raw)
    # The conditional gate refused to convert; downstream passes
    # also can't repair this. Should fail.
    if result is not None:
        # In case a future demjson3 fallback rescues this — verify
        # at least the apostrophe in Mike's file survived.
        parsed = json.loads(result)
        assert parsed.get("name") == "Mike's file"


# ---------------------------------------------------------------------------
# Trailing commas
# ---------------------------------------------------------------------------


def test_trailing_comma_in_object() -> None:
    raw = '{"a": 1, "b": 2,}'
    result, fixes = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"a": 1, "b": 2}
    assert any("trailing comma" in f for f in fixes)


def test_trailing_comma_in_array() -> None:
    raw = "[1, 2, 3,]"
    result, fixes = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == [1, 2, 3]


def test_trailing_comma_with_whitespace() -> None:
    raw = '{"a": 1,   \n}'
    result, _ = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"a": 1}


# ---------------------------------------------------------------------------
# Unquoted keys
# ---------------------------------------------------------------------------


def test_unquoted_keys_quoted() -> None:
    raw = "{foo: 1, bar: 2}"
    result, fixes = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"foo": 1, "bar": 2}
    assert any("unquoted keys" in f for f in fixes)


def test_unquoted_keys_with_string_values() -> None:
    raw = '{foo: "a", bar: "b"}'
    result, _ = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"foo": "a", "bar": "b"}


# ---------------------------------------------------------------------------
# Combined fixes
# ---------------------------------------------------------------------------


def test_combined_smart_quotes_and_trailing_comma() -> None:
    raw = "{“foo”: 1, “bar”: 2,}"
    result, fixes = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"foo": 1, "bar": 2}
    # Both passes should have applied.
    assert any("smart quotes" in f for f in fixes)
    assert any("trailing comma" in f for f in fixes)


def test_combined_single_quotes_unquoted_keys_trailing_comma() -> None:
    raw = "{foo: 'bar', baz: 'qux',}"
    result, _ = sanitize_tool_call_args(raw)
    assert result is not None
    assert json.loads(result) == {"foo": "bar", "baz": "qux"}


# ---------------------------------------------------------------------------
# Unrecoverable
# ---------------------------------------------------------------------------


def test_missing_close_brace_unrecoverable() -> None:
    """Truncated payload can't be safely recovered without speculating
    about what comes next — sanitizer returns None (unless demjson3 is
    installed AND rescues it, in which case the rescued value at least
    preserves the partial data we did see)."""
    raw = '{"a": 1'
    result, _ = sanitize_tool_call_args(raw)
    if result is not None:
        # demjson3 rescue path — at least confirm "a" survived.
        assert json.loads(result).get("a") == 1


def test_garbled_input_returns_none() -> None:
    raw = "not even close to json !@#$%"
    result, _ = sanitize_tool_call_args(raw)
    assert result is None


# ---------------------------------------------------------------------------
# Idempotence & logging contract
# ---------------------------------------------------------------------------


def test_idempotent_no_fixes_for_clean_input() -> None:
    """A fresh call on already-valid JSON records no fixes (the
    idempotence property: sanitize(sanitize(x)) == sanitize(x) at
    the fixes-list level)."""
    raw = '{"x": 1}'
    once, fixes_once = sanitize_tool_call_args(raw)
    assert once == raw
    assert fixes_once == []
    twice, fixes_twice = sanitize_tool_call_args(once)
    assert twice == raw
    assert fixes_twice == []


def test_tool_name_never_affects_output() -> None:
    """The tool_name is for logging only; it must not affect the
    sanitised value."""
    raw = "{foo: 1,}"
    r1, _ = sanitize_tool_call_args(raw, tool_name="Read")
    r2, _ = sanitize_tool_call_args(raw, tool_name="Write")
    assert r1 == r2
    assert r1 is not None
    assert json.loads(r1) == {"foo": 1}
