"""Provider ABC + StreamChunk + registry semantics."""

from __future__ import annotations

import pytest

import athena.providers as providers_pkg
from athena.providers import (
    Provider,
    StreamChunk,
    get_provider_class,
    list_providers,
    register_provider,
    unregister,
)

# ---- StreamChunk -------------------------------------------------------


def test_stream_chunk_kinds_construct():
    """All four canonical kinds round-trip cleanly."""
    c = StreamChunk("content", "hello")
    t = StreamChunk("tool_call", {"name": "Read", "arguments": {}, "id": "abc"})
    u = StreamChunk("usage", {"prompt_tokens": 12, "completion_tokens": 5})
    e = StreamChunk("end", {"reason": "stop"})
    assert c.kind == "content"
    assert c.payload == "hello"
    assert t.kind == "tool_call"
    assert t.payload["name"] == "Read"
    assert u.kind == "usage"
    assert e.kind == "end"


def test_stream_chunk_content_accessor():
    assert StreamChunk("content", "hi").content == "hi"
    assert StreamChunk("tool_call", {}).content == ""
    assert StreamChunk("usage", {"prompt_tokens": 1}).content == ""
    assert StreamChunk("end", {"reason": "stop"}).content == ""


# ---- Provider ABC ------------------------------------------------------


def test_provider_subclass_must_implement_stream_chat():
    class Missing(Provider):
        name = "missing-stream"

        def parse_tool_calls(self, content, raw_response):
            return content, []

        # No stream_chat — instantiation must fail.

    with pytest.raises(TypeError, match="abstract"):
        Missing()  # type: ignore[abstract]


def test_provider_subclass_must_implement_parse_tool_calls():
    class Missing(Provider):
        name = "missing-parse"

        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            if False:
                yield

        # No parse_tool_calls — instantiation must fail.

    with pytest.raises(TypeError, match="abstract"):
        Missing()  # type: ignore[abstract]


def test_complete_subclass_instantiates():
    class Complete(Provider):
        name = "complete-test"

        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            yield StreamChunk("end", {"reason": "stop"})

        def parse_tool_calls(self, content, raw_response):
            return content, []

    p = Complete(api_key="key")
    assert p.api_key == "key"
    chunks = list(p.stream_chat(model="x", messages=[]))
    assert chunks[0].kind == "end"


def test_count_tokens_default_heuristic():
    class P(Provider):
        name = "x"

        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            if False:
                yield

        def parse_tool_calls(self, content, raw_response):
            return content, []

    p = P()
    # Word-count / 0.75 → 6 words → 8 tokens.
    assert p.count_tokens("a b c d e f") == 8
    # Empty text → 0.
    assert p.count_tokens("") == 0
    # Single word never returns 0.
    assert p.count_tokens("hello") >= 1


def test_close_is_default_noop():
    class P(Provider):
        name = "noop"

        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            if False:
                yield

        def parse_tool_calls(self, content, raw_response):
            return content, []

    P().close()  # no exception, returns None


# ---- Registry ----------------------------------------------------------


def _scratch_provider(name: str) -> type[Provider]:
    """Build a minimal Provider subclass for registry tests."""

    class _Scratch(Provider):
        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            if False:
                yield

        def parse_tool_calls(self, content, raw_response):
            return content, []

    _Scratch.name = name
    return _Scratch


def test_register_and_lookup_roundtrip():
    cls = _scratch_provider("test-roundtrip")
    register_provider(cls)
    try:
        assert get_provider_class("test-roundtrip") is cls
        assert "test-roundtrip" in list_providers()
    finally:
        unregister("test-roundtrip")


def test_register_requires_nonempty_name():
    class Anon(Provider):
        name = ""

        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            if False:
                yield

        def parse_tool_calls(self, content, raw_response):
            return content, []

    with pytest.raises(ValueError, match="non-empty"):
        register_provider(Anon)


def test_register_decorator_returns_class():
    """``@register_provider`` should not silently drop the wrapped class."""
    cls = _scratch_provider("decorator-return")
    try:
        out = register_provider(cls)
        assert out is cls
    finally:
        unregister("decorator-return")


def test_register_overwrites_existing():
    """Re-registration replaces the prior class — test affordance."""
    a = _scratch_provider("dup")
    b = _scratch_provider("dup")
    register_provider(a)
    register_provider(b)
    try:
        assert get_provider_class("dup") is b
    finally:
        unregister("dup")


def test_get_provider_class_unknown_raises():
    with pytest.raises(KeyError) as excinfo:
        get_provider_class("definitely-not-a-real-provider")
    msg = str(excinfo.value)
    assert "definitely-not-a-real-provider" in msg
    assert "Available providers" in msg


def test_unregister_is_idempotent():
    """Idempotent: removing twice doesn't raise."""
    cls = _scratch_provider("transient")
    register_provider(cls)
    unregister("transient")
    unregister("transient")  # no exception
    assert "transient" not in list_providers()


def test_pkg_exports_canonical_symbols():
    """The top-level package exposes Provider, StreamChunk, and the
    registry helpers."""
    for name in (
        "Provider",
        "StreamChunk",
        "register_provider",
        "get_provider_class",
        "list_providers",
        "unregister",
    ):
        assert hasattr(providers_pkg, name), f"missing export: {name}"
