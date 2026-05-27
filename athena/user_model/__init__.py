"""User-modeling backend — auto-extracted observations about the
user and project, distinct from the user-authored memory store.

Pluggable: the default ``MarkdownUserModel`` writes facts to
``~/.athena/profiles/<profile>/user_model/`` as markdown files
mirroring the existing memory format. A future ``HonchoUserModel``
points at a Honcho instance for users who want server-side
fact extraction + retrieval at scale.

Public surface:

    UserModelBackend       — Protocol every backend implements
    IngestResult           — return value from ingest_session
    QueryResult            — return value from query
    BackendHealth          — return value from health
    get_user_model_backend — factory; reads cfg.user_model.backend
                             and returns a configured backend
"""

from __future__ import annotations

from .base import (
    BackendHealth,
    ExtractedFact,
    IngestResult,
    QueryResult,
    UserModelBackend,
)
from .factory import get_user_model_backend

__all__ = [
    "BackendHealth",
    "ExtractedFact",
    "IngestResult",
    "QueryResult",
    "UserModelBackend",
    "get_user_model_backend",
]
