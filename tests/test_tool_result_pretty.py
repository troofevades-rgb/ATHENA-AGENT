"""Tests for ``athena.ui._maybe_pretty_json`` — the tool-output
prettifier that turns one-line JSON dumps (search_x, browser tools,
status tools) into readable multi-line blocks for the transcript.

The transcript renderer truncates by LINE count; a single-line JSON
dump can't be line-truncated and lands in the UI as a wall of
escaped braces. This helper restores line structure when the output
parses as JSON.
"""

from __future__ import annotations

from athena.ui import _maybe_pretty_json


def test_pretty_prints_search_x_style_object() -> None:
    """The real-world case: ``search_x`` returns one-line JSON."""
    raw = (
        '{"available": true, "provider": "social", "results": '
        '[{"author": "alice", "text": "hello"}]}'
    )
    out = _maybe_pretty_json(raw)
    # Now multi-line
    assert "\n" in out
    # Top-level keys on their own indented lines
    assert '"available": true' in out
    assert '"provider": "social"' in out
    assert '"results"' in out
    # Nested object is also indented
    assert '"author": "alice"' in out


def test_pretty_prints_top_level_array() -> None:
    raw = '[{"id": 1}, {"id": 2}, {"id": 3}]'
    out = _maybe_pretty_json(raw)
    assert "\n" in out
    assert out.count('"id"') == 3


def test_plain_text_passes_through_unchanged() -> None:
    """Output that isn't JSON-shaped must NOT be touched."""
    plain = "just a plain string with no JSON shape"
    assert _maybe_pretty_json(plain) == plain


def test_text_with_braces_in_middle_passes_through() -> None:
    """Don't try to parse text that happens to contain ``{`` somewhere
    — only attempt parse if the trimmed text STARTS with ``{`` or ``[``
    AND ends with the matching closer."""
    weird = "Output: success {but the message contains a brace}"
    assert _maybe_pretty_json(weird) == weird


def test_empty_input_passes_through() -> None:
    assert _maybe_pretty_json("") == ""
    assert _maybe_pretty_json("   ") == "   "


def test_short_input_passes_through() -> None:
    """A few-char string isn't worth trying to parse."""
    assert _maybe_pretty_json("{}") == "{}"
    assert _maybe_pretty_json("[]") == "[]"


def test_malformed_json_passes_through() -> None:
    """Looks like JSON but doesn't parse — return original unchanged
    (don't crash, don't mangle)."""
    bad = '{"unclosed": "string'
    # Trailing closer makes the shape match, but parse will fail
    bad2 = '{"key": value-without-quotes}'
    assert _maybe_pretty_json(bad) == bad
    assert _maybe_pretty_json(bad2) == bad2


def test_json_primitive_at_top_level_passes_through() -> None:
    """A bare number or string parses as JSON but isn't worth
    pretty-printing. Pass through."""
    # These don't start with { or [ so they bypass the heuristic
    # and never reach the parse path. Still verify the contract.
    assert _maybe_pretty_json("42") == "42"
    assert _maybe_pretty_json('"hello"') == '"hello"'


def test_pretty_print_preserves_unicode() -> None:
    """ensure_ascii=False keeps emoji and CJK readable."""
    raw = '{"msg": "owl 🦉 and 中文"}'
    out = _maybe_pretty_json(raw)
    assert "🦉" in out
    assert "中文" in out
    # Did NOT escape to \uXXXX
    assert "\\u" not in out


def test_handles_leading_trailing_whitespace() -> None:
    """JSON dumps from some tools come with surrounding whitespace.
    Strip is OK; the content is what matters."""
    raw = '\n  {"a": 1, "b": 2}  \n'
    out = _maybe_pretty_json(raw)
    assert '"a": 1' in out
    assert "\n" in out  # got re-formatted


def test_does_not_pretty_print_when_lengths_dont_match_shape() -> None:
    """Object literal as text but not actually JSON syntax
    (e.g. Python repr) — pass through."""
    pyrepr = "{'a': 1, 'b': 2}"  # single quotes — JSON would need double
    assert _maybe_pretty_json(pyrepr) == pyrepr
