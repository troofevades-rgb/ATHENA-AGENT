"""Tests for ``athena.recall.embeddings`` — embedder construction,
vector coercion, model-id resolution.

The vector store + hybrid layers have their own test files; this
fills the gap for the ADAPTER between providers and the recall
pipeline. Coercion bugs here mean every semantic-recall query
fails or returns garbage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from athena.recall.embeddings import (
    Embedder,
    _coerce_vector,
    _resolve_model_id,
    resolve_embedder,
)


# ---------------------------------------------------------------------------
# _coerce_vector — provider response shape normalization
# ---------------------------------------------------------------------------


def test_coerce_bare_list_passes_through() -> None:
    """Ollama returns the bare vector."""
    out = _coerce_vector([0.1, 0.2, 0.3])
    assert out == [0.1, 0.2, 0.3]


def test_coerce_int_list_becomes_float_list() -> None:
    """Defensive: an int list (rare but seen in test stubs)
    must coerce to floats so downstream cosine similarity
    works without type juggling."""
    out = _coerce_vector([1, 2, 3])
    assert out == [1.0, 2.0, 3.0]
    assert all(isinstance(x, float) for x in out)


def test_coerce_dict_with_embedding_key() -> None:
    """Some local servers wrap the vector in an envelope."""
    out = _coerce_vector({"embedding": [0.5, 0.6]})
    assert out == [0.5, 0.6]


def test_coerce_openai_data_shape() -> None:
    """OpenAI's embeddings endpoint returns ``{data: [{embedding: [...]}]}``."""
    out = _coerce_vector({"data": [{"embedding": [0.7, 0.8, 0.9]}]})
    assert out == [0.7, 0.8, 0.9]


def test_coerce_unknown_shape_raises_clear_error() -> None:
    """A provider returning an unrecognized shape must raise a
    clear error rather than silently feeding garbage into the
    vector store. Pin the exception type so retry logic can
    classify it correctly."""
    with pytest.raises(ValueError, match="unexpected embedding response shape"):
        _coerce_vector(42)
    with pytest.raises(ValueError):
        _coerce_vector("not a vector")
    with pytest.raises(ValueError):
        _coerce_vector({"unrelated": "field"})


def test_coerce_empty_data_list_raises() -> None:
    """OpenAI envelope with empty data — defensive, don't silently
    return [] which would mix with real vectors."""
    with pytest.raises(ValueError):
        _coerce_vector({"data": []})


# ---------------------------------------------------------------------------
# Embedder.embed — provider method discovery
# ---------------------------------------------------------------------------


class _StubProvider:
    """Provider with an embed method that returns a fixed vector."""
    def __init__(self, method_name: str = "embed"):
        setattr(self, method_name, self._do_embed)
        self.calls: list[tuple[str, str]] = []
        self._method_name = method_name

    def _do_embed(self, text: str, model: str) -> list[float]:
        self.calls.append((text, model))
        return [0.1, 0.2, 0.3]


def test_embedder_finds_embed_method() -> None:
    """Ollama exposes ``embed``."""
    provider = _StubProvider("embed")
    embedder = Embedder(provider=provider, model_id="m")
    assert embedder.embed("hello") == [0.1, 0.2, 0.3]
    assert provider.calls == [("hello", "m")]


def test_embedder_finds_embeddings_method() -> None:
    """OpenAI exposes ``embeddings``."""
    provider = _StubProvider("embeddings")
    embedder = Embedder(provider=provider, model_id="m")
    assert embedder.embed("hello") == [0.1, 0.2, 0.3]


def test_embedder_finds_embed_text_method() -> None:
    """Third common naming convention."""
    provider = _StubProvider("embed_text")
    embedder = Embedder(provider=provider, model_id="m")
    assert embedder.embed("hello") == [0.1, 0.2, 0.3]


def test_embedder_prefers_embed_over_embeddings() -> None:
    """A provider with BOTH methods uses ``embed`` (first in the
    tried list). Pinning order prevents accidental swap during
    refactor."""
    class _Both:
        def embed(self, text, model):
            return [1.0]
        def embeddings(self, text, model):
            return [2.0]
    embedder = Embedder(provider=_Both(), model_id="m")
    assert embedder.embed("x") == [1.0]


def test_embedder_raises_when_provider_has_no_embed_method() -> None:
    """Anthropic doesn't have an embeddings API. If wired up by
    mistake, fail loudly with a message naming the class so the
    user can fix their config."""
    class _NoEmbed:
        pass
    embedder = Embedder(provider=_NoEmbed(), model_id="m")
    with pytest.raises(RuntimeError, match="_NoEmbed"):
        embedder.embed("hello")


def test_embedder_response_coerced_through_coerce_vector() -> None:
    """Provider returning OpenAI-style envelope still works —
    proves the embedder routes through _coerce_vector."""
    class _OpenAIShape:
        def embeddings(self, text, model):
            return {"data": [{"embedding": [0.9, 0.8]}]}
    embedder = Embedder(provider=_OpenAIShape(), model_id="m")
    assert embedder.embed("x") == [0.9, 0.8]


# ---------------------------------------------------------------------------
# _resolve_model_id — precedence ordering
# ---------------------------------------------------------------------------


@dataclass
class _CfgWithExplicit:
    embedding_model: str = "user-pinned-model"


@dataclass
class _CfgNoOverride:
    pass


class _BackendWithDeclared:
    name = "ollama"
    default_embedding_model = "nomic-embed-text"


class _BackendNoDeclared:
    name = "myprovider"


def test_resolve_model_id_explicit_cfg_wins() -> None:
    out = _resolve_model_id(_BackendWithDeclared, _CfgWithExplicit())
    assert out == "user-pinned-model"


def test_resolve_model_id_falls_back_to_backend_declared() -> None:
    out = _resolve_model_id(_BackendWithDeclared, _CfgNoOverride())
    assert out == "nomic-embed-text"


def test_resolve_model_id_namespaced_fallback_when_nothing_declared() -> None:
    """No cfg override, no backend declaration → ``<name>:embeddings``.
    Stable string the vector store can key on."""
    out = _resolve_model_id(_BackendNoDeclared, _CfgNoOverride())
    assert out == "myprovider:embeddings"


# ---------------------------------------------------------------------------
# resolve_embedder — registry lookup + instantiation failure
# ---------------------------------------------------------------------------


def test_resolve_embedder_returns_none_when_no_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No embeddings provider registered → None. Recall path
    degrades to keyword-only without complaining."""
    from athena import media as _media

    class _EmptyRegistry:
        def __init__(self, cfg): pass
        def backend_for(self, capability): return None

    monkeypatch.setattr(_media, "MediaRegistry", _EmptyRegistry)
    out = resolve_embedder(cfg=object())
    assert out is None


def test_resolve_embedder_returns_none_on_instantiation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hosted providers that need credentials raise on bare
    instantiation. resolve_embedder must catch and return None —
    don't propagate, don't crash the agent's session start."""
    from athena import media as _media

    class _FailingBackend:
        name = "hosted-thing"
        def __init__(self):
            raise RuntimeError("requires API key")

    class _Reg:
        def __init__(self, cfg): pass
        def backend_for(self, capability): return _FailingBackend

    monkeypatch.setattr(_media, "MediaRegistry", _Reg)
    out = resolve_embedder(cfg=object())
    assert out is None


def test_resolve_embedder_returns_populated_embedder_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: backend resolves, instantiates, returns an
    Embedder with the right model_id."""
    from athena import media as _media

    class _OkBackend:
        name = "ollama"
        default_embedding_model = "nomic-embed-text"
        def __init__(self): pass

    class _Reg:
        def __init__(self, cfg): pass
        def backend_for(self, capability): return _OkBackend

    monkeypatch.setattr(_media, "MediaRegistry", _Reg)
    out = resolve_embedder(cfg=object())
    assert out is not None
    assert out.model_id == "nomic-embed-text"
    assert isinstance(out.provider, _OkBackend)
