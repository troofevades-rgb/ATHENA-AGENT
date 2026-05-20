"""Embeddings adapter — resolve a provider via the T5-01 manifest (T6-01.1).

Athena's broader recall pipeline only needs two things from the
embedding layer:

  1. ``embed(text) -> list[float]`` — a vector
  2. ``model_id`` — a stable identifier stored alongside the
     vector so a model swap doesn't silently mix incomparable
     vectors at query time

This module wraps a resolved provider (via
:class:`athena.media.MediaRegistry`'s capability lookup) in an
:class:`Embedder` that exposes exactly those two pieces. Local
providers are preferred so the recall path stays offline when a
local embedding model is installed.

Returns None cleanly when no embeddings provider is registered
on this host — semantic recall then degrades to keyword-only
(no hard dependency).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Embedder:
    """Thin wrapper around the resolved provider's embedding call.

    The model_id is stored as part of the wrapper because the
    vector store keys on it — a vector embedded by model X is
    only ever compared against other model-X vectors. Mixing
    spaces silently is the worst-case failure for semantic
    recall.
    """

    provider: Any
    model_id: str

    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns the raw vector as a
        plain list of floats. The provider's own ``embed`` or
        ``embeddings`` method does the work; this adapter just
        normalises the return shape so downstream callers don't
        special-case per-provider response wrappers."""
        # Each provider class names its embedding method
        # differently (anthropic doesn't have one yet, ollama
        # exposes ``embed``, openai exposes ``embeddings``).
        # The simplest robust path: try common method names; fall
        # back to a clear error so a misconfigured provider
        # surfaces explicitly.
        for method_name in ("embed", "embeddings", "embed_text"):
            fn = getattr(self.provider, method_name, None)
            if callable(fn):
                vec = fn(text, model=self.model_id)
                return _coerce_vector(vec)
        raise RuntimeError(
            f"provider {type(self.provider).__name__} exposes no "
            "embedding method (tried: embed, embeddings, embed_text)"
        )


def resolve_embedder(*, cfg: Any) -> Embedder | None:
    """Resolve an embeddings :class:`Embedder` for the current host,
    or None when no provider declares the capability.

    Uses :class:`athena.media.MediaRegistry` so the broker's
    local-preference logic (`media_backend_prefer` / `embedding_model_prefer`)
    governs the choice. Local providers (Ollama with embedding
    models) win by default — recall stays offline when a local
    embedder is installed.

    Construction of the actual provider instance is *not* done
    here — that needs a credential pool and a configured client.
    The caller (typically session-start wiring) provides a
    constructed provider via the registry lookup or builds one
    on demand. This function returns the class metadata; the
    caller instantiates.
    """
    from ..media import MediaRegistry

    registry = MediaRegistry(cfg=cfg)
    backend_cls = registry.backend_for("embeddings")
    if backend_cls is None:
        logger.info(
            "recall: no embeddings backend registered; falling back to keyword-only"
        )
        return None
    model_id = _resolve_model_id(backend_cls, cfg)
    # Instantiate with kwargs the provider's __init__ expects.
    # Keyless local providers (Ollama, openai_compat) can take a
    # bare constructor; hosted ones can't be instantiated without
    # credentials and shouldn't end up here under default cfg
    # (local-preferred). When they do, we surface a clear None
    # rather than crashing.
    try:
        provider = backend_cls()
    except Exception as e:  # noqa: BLE001
        logger.info(
            "recall: could not instantiate embeddings backend %s: %s",
            backend_cls.name,
            e,
        )
        return None
    logger.info(
        "recall: embeddings backend resolved → %s (model=%s)",
        backend_cls.name,
        model_id,
    )
    return Embedder(provider=provider, model_id=model_id)


def _resolve_model_id(backend_cls: Any, cfg: Any) -> str:
    """Choose the embedding model id. Tries (in order):

      cfg.embedding_model       — explicit override
      backend_cls.default_embedding_model — provider-declared
      backend_cls.name + ":embeddings" — last-resort namespaced
                                          fallback

    The id only needs to be stable across writes + reads — its
    job is to scope vector comparisons, not to be human-meaningful.
    """
    explicit = getattr(cfg, "embedding_model", None)
    if explicit:
        return str(explicit)
    declared = getattr(backend_cls, "default_embedding_model", None)
    if declared:
        return str(declared)
    return f"{getattr(backend_cls, 'name', 'unknown')}:embeddings"


def _coerce_vector(raw: Any) -> list[float]:
    """Normalise the provider's embedding response to ``list[float]``.

    Common shapes observed across providers:

      - bare ``list[float]``
      - ``{"embedding": [floats]}``
      - ``{"data": [{"embedding": [floats]}]}`` (OpenAI shape)
    """
    if isinstance(raw, list):
        return [float(x) for x in raw]
    if isinstance(raw, dict):
        if "embedding" in raw and isinstance(raw["embedding"], list):
            return [float(x) for x in raw["embedding"]]
        if "data" in raw and isinstance(raw["data"], list) and raw["data"]:
            first = raw["data"][0]
            if isinstance(first, dict) and "embedding" in first:
                return [float(x) for x in first["embedding"]]
    raise ValueError(f"unexpected embedding response shape: {type(raw)!r}")
