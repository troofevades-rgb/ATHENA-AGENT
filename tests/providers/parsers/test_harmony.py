"""GPT-OSS harmony channel parser."""
from __future__ import annotations

from athena.providers.parsers.harmony import parse


def _harmony(*chunks: tuple[str, str, str]) -> str:
    """Helper: build a harmony-formatted string from (channel, message, terminator) tuples."""
    return "".join(
        f"<|channel|>{ch}<|message|>{msg}<|{term}|>"
        for ch, msg, term in chunks
    )


def test_final_channel_extracted():
    content = _harmony(("final", "The answer is 42.", "return"))
    cleaned, calls = parse(content, {})
    assert cleaned == "The answer is 42."
    assert calls == []


def test_commentary_tool_calls_extracted():
    content = _harmony(
        ("commentary", 'Read({"file_path": "/etc/hostname"})', "end"),
        ("final", "Done.", "return"),
    )
    cleaned, calls = parse(content, {})
    assert cleaned == "Done."
    assert len(calls) == 1
    assert calls[0]["name"] == "Read"
    assert calls[0]["arguments"] == {"file_path": "/etc/hostname"}


def test_analysis_channel_dropped():
    """Internal chain-of-thought from the analysis channel must never
    surface in cleaned_content or as a tool call."""
    content = _harmony(
        ("analysis", "Hmm, the user wants...", "end"),
        ("final", "OK.", "return"),
    )
    cleaned, calls = parse(content, {})
    assert "Hmm" not in cleaned
    assert cleaned == "OK."
    assert calls == []


def test_multiple_commentary_lines_as_separate_tool_calls():
    content = _harmony(
        ("commentary",
         'Read({"path": "a"})\n'
         'Read({"path": "b"})',
         "end"),
        ("final", "Both done.", "return"),
    )
    _, calls = parse(content, {})
    assert len(calls) == 2
    assert calls[0]["arguments"]["path"] == "a"
    assert calls[1]["arguments"]["path"] == "b"


def test_no_channels_treats_as_plain_content():
    """Content with no <|channel|> markers must pass through unchanged
    rather than getting mangled."""
    cleaned, calls = parse("just a plain response", {})
    assert cleaned == "just a plain response"
    assert calls == []


def test_partial_channels_handled_gracefully():
    """An incomplete channel structure (missing terminator) shouldn't
    crash — those channels just don't match and the rest of content
    flows through."""
    content = "<|channel|>final<|message|>incomplete..."
    cleaned, _ = parse(content, {})
    # Without a closing |end| or |return|, the channel pattern doesn't
    # match — content passes through.
    assert "incomplete" in cleaned


def test_commentary_with_malformed_args_wraps_raw():
    content = _harmony(
        ("commentary", "Read(not-valid-json)", "end"),
        ("final", "ok", "return"),
    )
    _, calls = parse(content, {})
    assert calls[0]["arguments"] == {"_raw": "not-valid-json"}


def test_commentary_with_empty_args():
    content = _harmony(
        ("commentary", "NoArgsTool()", "end"),
        ("final", "ok", "return"),
    )
    _, calls = parse(content, {})
    assert calls[0]["name"] == "NoArgsTool"
    assert calls[0]["arguments"] == {}


def test_parser_never_raises_on_garbage():
    parse("", {})
    parse("<|channel|>", {})
    parse("<|channel|>final<|message|><|return|>", {})
    parse(None, {})  # type: ignore[arg-type]
