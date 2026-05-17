"""resolve_provider — model → (provider, bare-model) routing."""
from __future__ import annotations

from pathlib import Path

import pytest

from athena.config import Config
from athena.providers import get_provider_class
from athena.providers.anthropic import AnthropicProvider
from athena.providers.credential_pool import Credential, CredentialPool
from athena.providers.google import GoogleProvider
from athena.providers.nous import NousProvider
from athena.providers.ollama import OllamaProvider
from athena.providers.openai import OpenAIProvider
from athena.providers.openai_compat import OpenAICompatProvider
from athena.providers.openrouter import OpenRouterProvider
from athena.providers.runtime_resolver import resolve_provider


@pytest.fixture
def empty_pool(tmp_path: Path) -> CredentialPool:
    return CredentialPool(tmp_path / "credentials.json")


@pytest.fixture
def filled_pool(tmp_path: Path) -> CredentialPool:
    p = CredentialPool(tmp_path / "credentials.json")
    for name in ("anthropic", "openai", "google", "openrouter", "nous"):
        p.add_credential(name, Credential(key=f"key-{name}-1"))
    return p


# ---- Explicit routing override ------------------------------------------


def test_explicit_routing_wins(filled_pool: CredentialPool):
    cfg = Config(providers={"routing": {"qwen-special": "anthropic"}})
    p, bare = resolve_provider("qwen-special", cfg, filled_pool)
    assert isinstance(p, AnthropicProvider)
    # No prefix to strip on a literal name — passes through as-is.
    assert bare == "qwen-special"
    p.close()


# ---- Prefix rules -------------------------------------------------------


def test_anthropic_prefix(filled_pool: CredentialPool):
    cfg = Config()
    p, bare = resolve_provider(
        "anthropic/claude-3-5-sonnet-20241022", cfg, filled_pool
    )
    assert isinstance(p, AnthropicProvider)
    # Prefix stripped — Anthropic API wants the bare name.
    assert bare == "claude-3-5-sonnet-20241022"
    p.close()


def test_openai_prefix(filled_pool: CredentialPool):
    cfg = Config()
    p, bare = resolve_provider("openai/gpt-4o-mini", cfg, filled_pool)
    assert isinstance(p, OpenAIProvider)
    assert bare == "gpt-4o-mini"
    p.close()


def test_google_prefix(filled_pool: CredentialPool):
    cfg = Config()
    p, bare = resolve_provider("google/gemini-1.5-pro", cfg, filled_pool)
    assert isinstance(p, GoogleProvider)
    assert bare == "gemini-1.5-pro"
    p.close()


def test_gemini_bare_prefix(filled_pool: CredentialPool):
    """'gemini-' alone routes to google without the explicit google/ prefix."""
    cfg = Config()
    p, bare = resolve_provider("gemini-1.5-flash", cfg, filled_pool)
    assert isinstance(p, GoogleProvider)
    assert bare == "gemini-1.5-flash"
    p.close()


def test_openrouter_prefix_preserves_inner_path(filled_pool: CredentialPool):
    """OpenRouter wants 'vendor/model' on the wire — don't strip below
    the leading 'openrouter/' segment."""
    cfg = Config()
    p, bare = resolve_provider(
        "openrouter/anthropic/claude-3-5-sonnet", cfg, filled_pool
    )
    assert isinstance(p, OpenRouterProvider)
    assert bare == "openrouter/anthropic/claude-3-5-sonnet"
    p.close()


def test_nous_prefix(filled_pool: CredentialPool):
    cfg = Config()
    p, bare = resolve_provider(
        "nous/Hermes-3-Llama-3.1-405B", cfg, filled_pool
    )
    assert isinstance(p, NousProvider)
    assert bare == "Hermes-3-Llama-3.1-405B"
    p.close()


# ---- openai_compat (host-in-model OR config-provided) -------------------


def test_host_port_model_routes_to_openai_compat(empty_pool: CredentialPool):
    cfg = Config(providers={"openai_compat": {"host": "http://vllm.local:8000"}})
    p, bare = resolve_provider(
        "vllm.local:8000/llama3", cfg, empty_pool,
    )
    assert isinstance(p, OpenAICompatProvider)
    # The "host:port/model" form passes through to the model arg as-is;
    # the openai_compat provider uses its own configured host.
    assert "llama3" in bare
    p.close()


def test_openai_compat_requires_host(empty_pool: CredentialPool):
    cfg = Config(providers={"routing": {"my-vllm-model": "openai_compat"}})
    # No providers.openai_compat.host configured — must raise.
    with pytest.raises(RuntimeError, match="openai_compat"):
        resolve_provider("my-vllm-model", cfg, empty_pool)


def test_openai_compat_no_credential_required(empty_pool: CredentialPool):
    """Local servers typically don't require auth; resolver shouldn't
    insist on a credential being in the pool."""
    cfg = Config(providers={
        "routing": {"my-vllm-model": "openai_compat"},
        "openai_compat": {"host": "http://vllm.local:8000"},
    })
    p, _ = resolve_provider("my-vllm-model", cfg, empty_pool)
    assert isinstance(p, OpenAICompatProvider)
    p.close()


# ---- Default: ollama ----------------------------------------------------


def test_bare_name_defaults_to_ollama(empty_pool: CredentialPool):
    cfg = Config()
    p, bare = resolve_provider("qwen2.5-coder:14b", cfg, empty_pool)
    assert isinstance(p, OllamaProvider)
    assert bare == "qwen2.5-coder:14b"
    p.close()


def test_ollama_uses_cfg_ollama_host_fallback(empty_pool: CredentialPool):
    """Legacy cfg.ollama_host is the fallback when providers.ollama.host
    isn't set — preserves backward compat with pre-Phase-8 configs."""
    cfg = Config(ollama_host="http://my-ollama.test:11434")
    p, _ = resolve_provider("llama3", cfg, empty_pool)
    assert isinstance(p, OllamaProvider)
    assert p.host == "http://my-ollama.test:11434"
    p.close()


def test_ollama_uses_providers_ollama_host_when_set(empty_pool: CredentialPool):
    """providers.ollama.host overrides the legacy cfg.ollama_host."""
    cfg = Config(
        ollama_host="http://legacy.test:11434",
        providers={"ollama": {"host": "http://new.test:11434"}},
    )
    p, _ = resolve_provider("llama3", cfg, empty_pool)
    assert p.host == "http://new.test:11434"
    p.close()


# ---- Credential-pool integration ----------------------------------------


def test_provider_constructed_with_credential_from_pool(filled_pool: CredentialPool):
    cfg = Config()
    p, _ = resolve_provider(
        "anthropic/claude-3-5-sonnet", cfg, filled_pool,
    )
    assert p.api_key == "key-anthropic-1"
    p.close()


def test_no_credential_for_hosted_provider_raises(empty_pool: CredentialPool):
    cfg = Config()
    with pytest.raises(RuntimeError, match="no credentials available"):
        resolve_provider("anthropic/claude-3-5-sonnet", cfg, empty_pool)


def test_credential_rotates_on_repeated_resolves(filled_pool: CredentialPool):
    """Sequential resolves of the same provider pull different credentials
    (round-robin) — the resolver shouldn't pin to one key."""
    filled_pool.add_credential("anthropic", Credential(key="key-anthropic-2"))
    cfg = Config()
    seen = set()
    for _ in range(4):
        p, _ = resolve_provider("anthropic/claude", cfg, filled_pool)
        seen.add(p.api_key)
        p.close()
    assert seen == {"key-anthropic-1", "key-anthropic-2"}


def test_base_url_override_passed_through(filled_pool: CredentialPool):
    """Per-provider base_url override (useful for staging, EU regions)."""
    cfg = Config(providers={"anthropic": {"base_url": "https://eu.anthropic.test/v1"}})
    p, _ = resolve_provider("anthropic/claude", cfg, filled_pool)
    assert p.base_url == "https://eu.anthropic.test/v1"
    p.close()
