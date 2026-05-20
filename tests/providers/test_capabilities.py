"""Tests for the Capabilities dataclass + ABC surface (T5-01R.2)."""

from __future__ import annotations

import dataclasses

import pytest

from athena.providers import Capabilities, get_provider_class
from athena.providers.base import Provider

# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


def test_capabilities_conservative_new_fields() -> None:
    """Behaviour-preserving defaults: new fields off; tool_calls
    + streaming on so the supports_* delegators stay True."""
    c = Capabilities()
    assert c.tool_calls is True
    assert c.streaming is True
    # All new opt-in fields default OFF
    assert c.vision is False
    assert c.prompt_caching is False
    assert c.cache_ttls_seconds == ()
    assert c.kv_cache_reuse is False
    assert c.structured_output is False
    assert c.embeddings is False
    assert c.is_local is False
    assert c.max_context_tokens is None
    assert c.max_image_edge_px is None
    assert c.native_format == "openai"


def test_capabilities_is_frozen() -> None:
    c = Capabilities()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.vision = True  # type: ignore[misc]


def test_capabilities_supports_by_name() -> None:
    c = Capabilities(vision=True)
    assert c.supports("vision") is True
    assert c.supports("embeddings") is False
    # Unknown capability → False (no AttributeError leakage)
    assert c.supports("nonexistent") is False


def test_capabilities_replace_round_trip() -> None:
    """`dataclasses.replace` works on frozen — important because
    `OllamaProvider.capabilities(model)` overrides will use it."""
    base = Capabilities()
    refined = dataclasses.replace(base, vision=True, max_image_edge_px=1024)
    assert refined.vision is True
    assert refined.max_image_edge_px == 1024
    # Base unchanged.
    assert base.vision is False


# ---------------------------------------------------------------------------
# Provider base methods
# ---------------------------------------------------------------------------


def test_provider_baseline_static_capabilities() -> None:
    """The base Provider's ``static_capabilities`` returns a default
    `Capabilities()`. Subclasses override; the base default exists
    so an un-declared subclass still has working
    supports_tools/supports_streaming."""
    caps = Provider.static_capabilities()
    assert isinstance(caps, Capabilities)
    assert caps.tool_calls is True and caps.streaming is True


def test_capabilities_instance_defaults_to_class() -> None:
    """`provider.capabilities(model)` returns the class baseline
    unless overridden."""
    # Use Ollama because it has a no-key ctor — we don't need network.
    OllamaProvider = get_provider_class("ollama")
    inst = OllamaProvider(host="http://127.0.0.1:11434")
    try:
        caps = inst.capabilities()
        assert isinstance(caps, Capabilities)
    finally:
        inst.close()


# ---------------------------------------------------------------------------
# Per-provider manifests (T5-01R.3)
# ---------------------------------------------------------------------------


def test_ollama_declares_local_and_kv_reuse() -> None:
    from athena.providers.ollama import OllamaProvider

    c = OllamaProvider.static_capabilities()
    assert c.is_local is True
    assert c.kv_cache_reuse is True
    assert c.prompt_caching is False  # no server-side cache
    assert c.embeddings is True
    assert c.native_format == "ollama"


def test_ollama_vision_is_model_dependent() -> None:
    """The Ollama manifest's maximal vision=True narrows per model
    via :meth:`capabilities(model)`."""
    from athena.providers.ollama import OllamaProvider

    p = OllamaProvider(host="http://127.0.0.1:11434")
    try:
        assert p.capabilities("llava").vision is True
        assert p.capabilities("llava:13b").vision is True
        assert p.capabilities("llama3.2-vision:11b").vision is True
        assert p.capabilities("qwen2.5-coder:14b").vision is False
        assert p.capabilities("nomic-embed-text").vision is False
        # No-arg defaults to the (maximal) static set.
        assert p.capabilities().vision is True
    finally:
        p.close()


def test_anthropic_declares_caching_ttls() -> None:
    from athena.providers.anthropic import AnthropicProvider

    c = AnthropicProvider.static_capabilities()
    assert c.prompt_caching is True
    assert c.cache_ttls_seconds == (300, 3600)
    assert c.vision is True
    assert c.max_image_edge_px == 1568
    assert c.native_format == "anthropic"


def test_openai_declares_embeddings_and_vision() -> None:
    from athena.providers.openai import OpenAIProvider

    c = OpenAIProvider.static_capabilities()
    assert c.embeddings is True
    assert c.vision is True
    assert c.prompt_caching is True
    assert c.native_format == "openai"


def test_google_declares_long_context() -> None:
    from athena.providers.google import GoogleProvider

    c = GoogleProvider.static_capabilities()
    assert c.max_context_tokens == 1_000_000
    assert c.vision is True
    assert c.native_format == "google"


def test_openrouter_claims_broad_set() -> None:
    """OpenRouter passes through many upstreams; the static set is
    the union of common capabilities."""
    from athena.providers.openrouter import OpenRouterProvider

    c = OpenRouterProvider.static_capabilities()
    assert c.tool_calls is True
    assert c.streaming is True
    assert c.vision is True
    assert c.prompt_caching is True


def test_nous_claims_caching() -> None:
    from athena.providers.nous import NousProvider

    c = NousProvider.static_capabilities()
    assert c.prompt_caching is True
    assert c.vision is False  # not on the portal surface


def test_openai_compat_conservative() -> None:
    """OpenAI-compat is host-defined; declared capabilities are
    only what's universally true for /v1/chat/completions."""
    from athena.providers.openai_compat import OpenAICompatProvider

    c = OpenAICompatProvider.static_capabilities()
    assert c.tool_calls is True
    assert c.streaming is True
    assert c.vision is False
    assert c.embeddings is False
    assert c.prompt_caching is False


def test_base_provider_baseline_preserves_supports() -> None:
    """The parity contract one more time: with the default base
    Capabilities, supports_tools and supports_streaming both
    return True. This is the same assertion as the parity test
    but reframed against the new method surface."""

    class _MinSubclass(Provider):
        name = "test-min"
        requires_api_key = False

        def stream_chat(self, **_):  # type: ignore[override]
            yield from ()

        def parse_tool_calls(self, content, raw_response):  # type: ignore[override]
            return content, []

    inst = _MinSubclass()
    assert inst.supports_tools("any") is True
    assert inst.supports_streaming("any") is True
    assert inst.capabilities("any") == Capabilities()
