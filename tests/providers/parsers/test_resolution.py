"""Parser registry resolution semantics."""

from __future__ import annotations

import pytest

import athena.providers.parsers as parsers_mod
from athena.providers.parsers import (
    Parser,
    register,
    register_default,
    resolve_parser,
)


@pytest.fixture
def isolated_registry():
    """Snapshot + restore the global registry around each test so
    parser-resolution tests stay hermetic."""
    saved_entries = list(parsers_mod._REGISTRY)
    saved_defaults = dict(parsers_mod._DEFAULTS)
    parsers_mod._REGISTRY.clear()
    parsers_mod._DEFAULTS.clear()
    yield
    parsers_mod._REGISTRY[:] = saved_entries
    parsers_mod._DEFAULTS.clear()
    parsers_mod._DEFAULTS.update(saved_defaults)


def _named_parser(name: str) -> Parser:
    """A parser that returns its own name in ``cleaned_content`` so tests
    can detect which one fired."""

    def _p(content, raw):
        return name, []

    return _p


def test_specific_glob_beats_default(isolated_registry):
    """A (provider, narrow-glob) entry takes priority over the
    provider-wide default."""
    register("anthropic", "claude-3-5-haiku-*", _named_parser("specific"))
    register_default("anthropic", _named_parser("default"))
    parser = resolve_parser("anthropic", "claude-3-5-haiku-20251001")
    out, _ = parser("anything", {})
    assert out == "specific"


def test_first_registration_wins(isolated_registry):
    """When two globs both match, the one registered FIRST returns.
    Order is the only disambiguator."""
    register("openai", "gpt-4*", _named_parser("wide"))
    register("openai", "gpt-4o", _named_parser("narrow"))
    parser = resolve_parser("openai", "gpt-4o")
    out, _ = parser("x", {})
    assert out == "wide"  # registered first


def test_provider_default_used_when_no_glob_matches(isolated_registry):
    """No (provider, glob) entry hits; fall through to register_default."""
    register("openai", "gpt-5*", _named_parser("never"))
    register_default("openai", _named_parser("default"))
    parser = resolve_parser("openai", "gpt-4o")
    out, _ = parser("x", {})
    assert out == "default"


def test_unmatched_provider_returns_global_fallback(isolated_registry):
    """No registry entry, no provider default; resolve_parser falls back
    to the always-present global fallback_parser. The fallback returns
    (content, []) for inputs without recognizable native tool calls."""
    parser = resolve_parser("definitely-not-a-real-provider", "any-model")
    cleaned, tool_calls = parser("plain prose", {})
    assert cleaned == "plain prose"
    assert tool_calls == []


def test_glob_match_is_case_insensitive(isolated_registry):
    """User config might say 'QWEN*'; the lookup should still match
    'qwen2.5-coder:14b' because fnmatch on lowercase both sides."""
    register("ollama", "QWEN*", _named_parser("matched"))
    parser = resolve_parser("ollama", "qwen2.5-coder:14b")
    out, _ = parser("x", {})
    assert out == "matched"


def test_provider_mismatch_skips_entry(isolated_registry):
    """A glob that matches the model name but on a different provider
    must not fire."""
    register("openai", "qwen*", _named_parser("wrong-provider"))
    register_default("ollama", _named_parser("ollama-default"))
    parser = resolve_parser("ollama", "qwen2.5-coder:14b")
    out, _ = parser("x", {})
    assert out == "ollama-default"


def test_empty_model_falls_through_to_default(isolated_registry):
    """No model string at all — resolver should still find the provider
    default rather than crashing on the fnmatch."""
    register_default("ollama", _named_parser("default"))
    parser = resolve_parser("ollama", "")
    out, _ = parser("x", {})
    assert out == "default"


def test_resolve_parser_returns_callable():
    """Even without any registered parsers, resolve_parser returns
    something callable — guaranteed by the global fallback."""
    parser = resolve_parser("unknown", "unknown")
    assert callable(parser)
