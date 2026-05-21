"""Tests for capability query helpers (T5-01R.4)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from athena.providers import (
    Capabilities,
    best_provider_for,
    capability_matrix,
    list_providers,
    providers_with_capability,
)
from athena.providers.runtime_resolver import available_providers_with_capability

# ---------------------------------------------------------------------------
# capability_matrix
# ---------------------------------------------------------------------------


def test_capability_matrix_covers_all_registered() -> None:
    matrix = capability_matrix()
    assert set(matrix) == set(list_providers())
    for name, caps in matrix.items():
        assert isinstance(caps, Capabilities), name


def test_capability_matrix_includes_expected_signals() -> None:
    matrix = capability_matrix()
    # Anthropic should declare prompt_caching True; openai_compat shouldn't.
    assert matrix["anthropic"].prompt_caching is True
    assert matrix["openai_compat"].prompt_caching is False
    # Local-declaring providers: ollama (chat) + stub_video_local
    # (capability-only, T6-05.2). The set grows as more local
    # capability providers are registered — pin both today's
    # declarers.
    locals_set = {n for n, c in matrix.items() if c.is_local}
    assert "ollama" in locals_set
    assert "stub_video_local" in locals_set


# ---------------------------------------------------------------------------
# providers_with_capability
# ---------------------------------------------------------------------------


def test_providers_with_capability_vision() -> None:
    """Vision-capable providers per T5-01R.3 declarations."""
    v = set(providers_with_capability("vision"))
    # Anthropic, OpenAI, Google, OpenRouter, Ollama (maximal) declare vision.
    assert "anthropic" in v
    assert "openai" in v
    assert "google" in v
    assert "openrouter" in v
    assert "ollama" in v  # static maximal set
    # Nous + openai_compat don't declare vision.
    assert "nous" not in v
    assert "openai_compat" not in v


def test_providers_with_capability_embeddings() -> None:
    """Embeddings — only providers with a dedicated embeddings endpoint."""
    e = set(providers_with_capability("embeddings"))
    assert "openai" in e
    assert "ollama" in e
    assert "anthropic" not in e


def test_providers_with_capability_prompt_caching() -> None:
    """Server-side prompt caching."""
    pc = set(providers_with_capability("prompt_caching"))
    assert "anthropic" in pc
    assert "openai" in pc
    assert "nous" in pc
    assert "openrouter" in pc
    assert "ollama" not in pc  # local kv reuse, not server-side


def test_providers_with_capability_kv_cache_reuse() -> None:
    """KV-cache reuse — local-machine prefix cache. Only Ollama
    declares this today."""
    assert providers_with_capability("kv_cache_reuse") == ["ollama"]


def test_providers_with_capability_unknown_returns_empty() -> None:
    assert providers_with_capability("nonexistent_cap") == []


def test_providers_with_capability_returns_sorted() -> None:
    names = providers_with_capability("tool_calls")  # all 7 declare True
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# best_provider_for
# ---------------------------------------------------------------------------


def test_best_provider_for_basic() -> None:
    """Returns the alphabetically-first qualifying provider when no
    preference is set."""
    name = best_provider_for({"vision"})
    assert name is not None
    # First alpha among the vision providers.
    assert name == sorted(providers_with_capability("vision"))[0]


def test_best_provider_for_prefers_when_qualifying() -> None:
    name = best_provider_for({"embeddings"}, prefer="ollama")
    assert name == "ollama"


def test_best_provider_for_prefers_ignored_when_not_qualifying() -> None:
    """`prefer="ollama"` for a capability ollama doesn't declare
    should fall back to the alpha-first qualifying name."""
    name = best_provider_for({"prompt_caching"}, prefer="ollama")
    assert name != "ollama"
    assert name == sorted(providers_with_capability("prompt_caching"))[0]


def test_best_provider_for_none_when_unsatisfiable() -> None:
    assert best_provider_for({"nonexistent_cap"}) is None


def test_best_provider_for_multi_need() -> None:
    """Both vision AND embeddings — narrows the candidates."""
    name = best_provider_for({"vision", "embeddings"})
    # openai + ollama both declare both → alpha-first is ollama
    assert name == "ollama"


# ---------------------------------------------------------------------------
# available_providers_with_capability — credential-aware
# ---------------------------------------------------------------------------


class _FakePool:
    """Pool stub: ``providers_with_creds`` lists names that return
    a credential from get()."""

    def __init__(self, providers_with_creds: set[str]):
        self._creds = providers_with_creds

    def get(self, name: str):
        if name in self._creds:
            return SimpleNamespace(key="dummy", label="test")
        return None


def test_available_filters_to_credentialed() -> None:
    """Only providers with credentials (or no-key providers) are
    listed."""
    pool = _FakePool(providers_with_creds={"anthropic"})
    cfg = SimpleNamespace(providers={})
    out = available_providers_with_capability("vision", cfg=cfg, pool=pool)
    # anthropic (credentialed, declares vision) + ollama (no key
    # needed, declares vision) should appear.
    assert "anthropic" in out
    assert "ollama" in out
    # google declares vision but has no credential — excluded.
    assert "google" not in out
    # openai_compat doesn't declare vision — excluded for that reason.
    assert "openai_compat" not in out


def test_available_with_no_credentials_keeps_local_providers() -> None:
    pool = _FakePool(providers_with_creds=set())
    cfg = SimpleNamespace(providers={})
    # Without any credentials, only the no-key providers (ollama,
    # openai_compat) remain. Both can do tool_calls. Ollama declares
    # embeddings; openai_compat doesn't.
    out = available_providers_with_capability("embeddings", cfg=cfg, pool=pool)
    assert out == ["ollama"]


def test_available_with_full_credentials_includes_hosted() -> None:
    pool = _FakePool(providers_with_creds={"anthropic", "openai", "google", "openrouter", "nous"})
    cfg = SimpleNamespace(providers={})
    out = available_providers_with_capability("prompt_caching", cfg=cfg, pool=pool)
    # All five hosted providers with prompt_caching declared land.
    for n in ("anthropic", "openai", "nous", "openrouter"):
        assert n in out


def test_available_returns_sorted() -> None:
    pool = _FakePool(providers_with_creds={"anthropic", "openai"})
    cfg = SimpleNamespace(providers={})
    out = available_providers_with_capability("vision", cfg=cfg, pool=pool)
    assert out == sorted(out)
