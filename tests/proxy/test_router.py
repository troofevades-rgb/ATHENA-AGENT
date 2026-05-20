"""Tests for athena.proxy.router (T3-01.3)."""

from __future__ import annotations

import pytest

from athena.proxy.router import RouteError, route_request


def test_provider_header_overrides_default() -> None:
    provider, model = route_request(
        requested_model="some-model",
        provider_header="openai",
        default_provider="anthropic",
        available_providers=["anthropic", "openai"],
    )
    assert provider == "openai"
    assert model == "some-model"


def test_provider_header_ignored_if_unavailable() -> None:
    """Header names a provider that isn't set up — fall through to the
    model-match path. The header should NOT hard-fail."""
    provider, _ = route_request(
        requested_model="claude-opus-4-7",
        provider_header="openai",
        default_provider="ollama",
        available_providers=["anthropic", "ollama"],
    )
    assert provider == "anthropic"


def test_provider_header_case_insensitive() -> None:
    provider, _ = route_request(
        requested_model="x",
        provider_header="ANTHROPIC",
        default_provider="ollama",
        available_providers=["anthropic", "ollama"],
    )
    assert provider == "anthropic"


def test_model_name_matches_anthropic_models() -> None:
    for m in ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"):
        provider, _ = route_request(
            requested_model=m,
            provider_header=None,
            default_provider="ollama",
            available_providers=["anthropic", "ollama"],
        )
        assert provider == "anthropic", m


def test_model_name_matches_openai_models() -> None:
    for m in ("gpt-4o", "gpt-4o-mini", "gpt-4.1"):
        provider, _ = route_request(
            requested_model=m,
            provider_header=None,
            default_provider="ollama",
            available_providers=["openai", "ollama"],
        )
        assert provider == "openai", m


def test_unknown_model_falls_back_to_default() -> None:
    provider, model = route_request(
        requested_model="some-random-model",
        provider_header=None,
        default_provider="anthropic",
        available_providers=["anthropic", "openrouter"],
    )
    assert provider == "anthropic"
    assert model == "some-random-model"


def test_unavailable_default_raises_route_error() -> None:
    with pytest.raises(RouteError, match="default provider"):
        route_request(
            requested_model="x",
            provider_header=None,
            default_provider="openai",
            available_providers=["ollama"],
        )


def test_openrouter_accepts_any_model() -> None:
    """OpenRouter's empty model list means it doesn't claim models
    by name; routing still works via the header override or by being
    the default."""
    provider, _ = route_request(
        requested_model="anthropic/claude-sonnet-4-6",
        provider_header="openrouter",
        default_provider="ollama",
        available_providers=["openrouter", "ollama"],
    )
    assert provider == "openrouter"

    # And via default
    provider, _ = route_request(
        requested_model="some/vendor/model",
        provider_header=None,
        default_provider="openrouter",
        available_providers=["openrouter"],
    )
    assert provider == "openrouter"


def test_ollama_accepts_any_model() -> None:
    """Ollama's empty list works the same as openrouter — header
    override or default fallback."""
    provider, _ = route_request(
        requested_model="qwen2.5-coder:14b",
        provider_header="ollama",
        default_provider="anthropic",
        available_providers=["ollama", "anthropic"],
    )
    assert provider == "ollama"


def test_model_match_skips_unavailable_provider() -> None:
    """If the model matches anthropic but anthropic isn't available,
    fall through to the default."""
    provider, _ = route_request(
        requested_model="claude-opus-4-7",
        provider_header=None,
        default_provider="openrouter",
        available_providers=["openrouter"],
    )
    assert provider == "openrouter"
