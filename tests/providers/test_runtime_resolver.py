"""resolve_provider — model → (provider, bare-model) routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.config import Config
from athena.providers.anthropic import AnthropicProvider
from athena.providers.credential_pool import Credential, CredentialPool
from athena.providers.google import GoogleProvider
from athena.providers.nous import NousProvider
from athena.providers.ollama import OllamaProvider
from athena.providers.openai import OpenAIProvider
from athena.providers.openai_compat import OpenAICompatProvider
from athena.providers.openrouter import OpenRouterProvider
from athena.providers.runtime_resolver import resolve_provider
from athena.providers.xai import XAIProvider


@pytest.fixture
def empty_pool(tmp_path: Path) -> CredentialPool:
    return CredentialPool(tmp_path / "credentials.json")


@pytest.fixture
def filled_pool(tmp_path: Path) -> CredentialPool:
    p = CredentialPool(tmp_path / "credentials.json")
    for name in ("anthropic", "openai", "google", "openrouter", "nous", "xai"):
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
    p, bare = resolve_provider("anthropic/claude-3-5-sonnet-20241022", cfg, filled_pool)
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


def test_openrouter_prefix_stripped_for_vendor_model_form(filled_pool: CredentialPool):
    """The leading ``openrouter/`` is a routing hint; OpenRouter's
    ``/chat/completions`` rejects it on the wire ("not a valid model
    ID" 400). For ``vendor/model`` catalog entries, strip the one
    routing prefix so the bare vendor/model lands at the API."""
    cfg = Config()
    p, bare = resolve_provider("openrouter/anthropic/claude-3-5-sonnet", cfg, filled_pool)
    assert isinstance(p, OpenRouterProvider)
    assert bare == "anthropic/claude-3-5-sonnet"
    p.close()


def test_openrouter_meta_router_models_kept_via_doubled_prefix(
    filled_pool: CredentialPool,
):
    """The five OpenRouter meta-router models (``openrouter/auto``,
    ``openrouter/free``, ``openrouter/owl-alpha``, etc.) LITERALLY
    start with ``openrouter/`` in their model id. To route them
    through this stack, the picker prefixes once and the catalog
    entry already starts with ``openrouter/``, yielding the doubled
    form. After stripping one routing prefix, the API sees the
    correct ``openrouter/auto`` form."""
    cfg = Config()
    p, bare = resolve_provider("openrouter/openrouter/auto", cfg, filled_pool)
    assert isinstance(p, OpenRouterProvider)
    assert bare == "openrouter/auto"
    p.close()


def test_openrouter_vendor_model_user_case(filled_pool: CredentialPool):
    """Specific case from a real failed call: nousresearch/hermes-4-405b
    sent as ``openrouter/nousresearch/hermes-4-405b`` (the picker's
    routing form) must reach the API as ``nousresearch/hermes-4-405b``."""
    cfg = Config()
    p, bare = resolve_provider("openrouter/nousresearch/hermes-4-405b", cfg, filled_pool)
    assert isinstance(p, OpenRouterProvider)
    assert bare == "nousresearch/hermes-4-405b"
    p.close()


def test_nous_prefix(filled_pool: CredentialPool):
    cfg = Config()
    p, bare = resolve_provider("nous/Hermes-3-Llama-3.1-405B", cfg, filled_pool)
    assert isinstance(p, NousProvider)
    assert bare == "Hermes-3-Llama-3.1-405B"
    p.close()


def test_xai_prefix(filled_pool: CredentialPool):
    cfg = Config()
    p, bare = resolve_provider("xai/grok-2-1212", cfg, filled_pool)
    assert isinstance(p, XAIProvider)
    assert bare == "grok-2-1212"
    p.close()


def test_grok_bare_prefix(filled_pool: CredentialPool):
    """'grok-' alone routes to xai without the explicit xai/ prefix --
    mirrors the gemini-/codex- bare-prefix convention so operators
    can use the model name they see in xAI's docs verbatim."""
    cfg = Config()
    p, bare = resolve_provider("grok-2-vision-1212", cfg, filled_pool)
    assert isinstance(p, XAIProvider)
    assert bare == "grok-2-vision-1212"
    p.close()


# ---- openai_compat (host-in-model OR config-provided) -------------------


def test_host_port_model_routes_to_openai_compat(empty_pool: CredentialPool):
    cfg = Config(providers={"openai_compat": {"host": "http://vllm.local:8000"}})
    p, bare = resolve_provider(
        "vllm.local:8000/llama3",
        cfg,
        empty_pool,
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
    cfg = Config(
        providers={
            "routing": {"my-vllm-model": "openai_compat"},
            "openai_compat": {"host": "http://vllm.local:8000"},
        }
    )
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
        "anthropic/claude-3-5-sonnet",
        cfg,
        filled_pool,
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


# ---- Fallback chain -----------------------------------------------------


def test_fallback_walks_when_primary_has_no_credential(empty_pool: CredentialPool):
    """anthropic primary has no key; fall back to openrouter which does."""
    empty_pool.add_credential("openrouter", Credential(key="sk-or-fallback"))
    cfg = Config(
        providers={
            "anthropic": {"fallback": ["openrouter"]},
        }
    )
    p, bare = resolve_provider("anthropic/claude-opus-4-7", cfg, empty_pool)
    # Provider class is OpenRouter's (the fallback), not Anthropic's.
    assert p.name == "openrouter"
    # Original model string passes through — OpenRouter takes vendor/model.
    assert bare == "anthropic/claude-opus-4-7"
    assert p.api_key == "sk-or-fallback"
    p.close()


def test_fallback_chain_walks_in_order(empty_pool: CredentialPool):
    """First fallback also empty; resolver walks to the second."""
    empty_pool.add_credential("openrouter", Credential(key="key-or"))
    cfg = Config(
        providers={
            "anthropic": {"fallback": ["openai", "openrouter"]},
        }
    )
    p, _ = resolve_provider("anthropic/claude", cfg, empty_pool)
    assert p.name == "openrouter"
    p.close()


def test_fallback_with_model_override(empty_pool: CredentialPool):
    """A {provider, model} dict entry lets the user remap the model string
    for the fallback (useful when falling back to ollama, where the
    original vendor/model form isn't valid)."""
    cfg = Config(
        ollama_host="http://localhost:11434",
        providers={
            "anthropic": {
                "fallback": [
                    {"provider": "ollama", "model": "qwen2.5-coder:14b"},
                ]
            },
        },
    )
    p, bare = resolve_provider("anthropic/claude", cfg, empty_pool)
    assert isinstance(p, OllamaProvider)
    assert bare == "qwen2.5-coder:14b"
    p.close()


def test_fallback_exhausted_raises_helpful_error(empty_pool: CredentialPool):
    """No credential anywhere in the chain — final error names every
    provider attempted."""
    cfg = Config(
        providers={
            "anthropic": {"fallback": ["openai", "openrouter"]},
        }
    )
    with pytest.raises(RuntimeError) as excinfo:
        resolve_provider("anthropic/claude", cfg, empty_pool)
    msg = str(excinfo.value)
    assert "anthropic" in msg
    # Every attempt name appears in the error so the user can correct.
    for name in ("anthropic", "openai", "openrouter"):
        assert name in msg


def test_fallback_skipped_when_primary_has_credential(filled_pool: CredentialPool):
    """Don't fall back when the primary works — even if a fallback is
    configured, the primary is the right answer."""
    cfg = Config(
        providers={
            "anthropic": {"fallback": ["openrouter"]},
        }
    )
    p, _ = resolve_provider("anthropic/claude-opus-4-7", cfg, filled_pool)
    assert p.name == "anthropic"
    p.close()


def test_fallback_does_not_swallow_config_errors(empty_pool: CredentialPool):
    """openai_compat missing host is a config error, not credential
    unavailability. It must NOT trigger fallback — the user typo'd."""
    cfg = Config(
        providers={
            # Route this model to openai_compat but don't configure host.
            "routing": {"my-model": "openai_compat"},
            # Even with a fallback configured, missing-host should raise.
            "openai_compat": {"fallback": ["openrouter"]},
        }
    )
    empty_pool.add_credential("openrouter", Credential(key="k"))
    with pytest.raises(RuntimeError, match="openai_compat"):
        resolve_provider("my-model", cfg, empty_pool)


def test_fallback_chain_malformed_entry_skipped(empty_pool: CredentialPool, caplog):
    """A typo'd entry (None, int, missing 'provider' key) is skipped with
    a logged warning. The rest of the chain still works."""
    empty_pool.add_credential("openrouter", Credential(key="k"))
    cfg = Config(
        providers={
            "anthropic": {
                "fallback": [
                    None,  # not a string or dict
                    {"not_provider": "openrouter"},  # missing 'provider' key
                    "openrouter",  # valid; should be reached
                ]
            },
        }
    )
    import logging

    with caplog.at_level(logging.WARNING):
        p, _ = resolve_provider("anthropic/claude", cfg, empty_pool)
    assert p.name == "openrouter"
    p.close()


def test_fallback_when_all_credentials_in_cooldown(tmp_path):
    """The pool.get None path covers both 'no credential' and 'all in
    cooldown' — both should trigger fallback walking."""
    from athena.providers.credential_pool import Credential, CredentialPool

    p = CredentialPool(tmp_path / "c.json", cooldown_seconds=600)
    p.add_credential("anthropic", Credential(key="k1"))
    p.add_credential("openrouter", Credential(key="or-key"))
    p.mark_429("anthropic", "k1")  # primary in cooldown

    cfg = Config(providers={"anthropic": {"fallback": ["openrouter"]}})
    provider, _ = resolve_provider("anthropic/claude", cfg, p)
    assert provider.name == "openrouter"
    provider.close()
