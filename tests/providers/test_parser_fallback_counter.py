"""Parser-fallback canary: resolve_parser counts (provider, model)
resolutions that fall through to the last-resort parser, and /status
surfaces them.
"""

from __future__ import annotations

from athena.cli.status import render_status
from athena.providers import parsers


def test_fallback_increments_per_provider_model() -> None:
    parsers.reset_fallback_counts()
    try:
        parsers.resolve_parser("no-such-provider", "weird-model")
        parsers.resolve_parser("no-such-provider", "weird-model")
        parsers.resolve_parser("no-such-provider", "other-model")
        counts = parsers.fallback_counts()
        assert counts[("no-such-provider", "weird-model")] == 2
        assert counts[("no-such-provider", "other-model")] == 1
    finally:
        parsers.reset_fallback_counts()


def test_known_provider_default_does_not_count() -> None:
    parsers.reset_fallback_counts()
    try:
        # ollama registers a provider-default parser — no fallback.
        parsers.resolve_parser("ollama", "llama3.1")
        assert parsers.fallback_counts() == {}
    finally:
        parsers.reset_fallback_counts()


def test_reset_clears_counts() -> None:
    parsers.resolve_parser("ghost-provider", "m")
    assert parsers.fallback_counts()
    parsers.reset_fallback_counts()
    assert parsers.fallback_counts() == {}


def test_render_status_shows_fallback_block() -> None:
    out = render_status({"parser_fallbacks": {"ghost/model-x": 3}})
    assert "parser fallbacks" in out
    assert "ghost/model-x" in out
    assert "3" in out


def test_render_status_omits_block_when_empty() -> None:
    assert "parser fallbacks" not in render_status({"profile": "default"})
