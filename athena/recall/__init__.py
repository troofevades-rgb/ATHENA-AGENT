"""Semantic recall (T6-01).

Layer on top of athena's existing FTS5-backed ``search_sessions``
that adds embedding-based retrieval and a reciprocal-rank-fusion
hybrid ranker. Resolves an embeddings provider via the T5-01
capability manifest — local-preferred so the entire recall path
can run offline with a local embedding model.

The keyword path is untouched; semantic is additive. Falls back
to keyword-only when no embeddings provider is available, so
recall never breaks because of a missing optional component.
"""

from .embeddings import Embedder, resolve_embedder
from .hybrid import rrf_fuse

__all__ = ["Embedder", "resolve_embedder", "rrf_fuse"]
