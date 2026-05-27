"""Protocol + dataclasses for the user-modeling backend.

The Protocol is intentionally small (ingest, query, health). Anything
richer — Honcho's peer cards, reasoning trees, observer/observed
splits — is backend-internal and doesn't leak through this seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# A transcript is the same shape athena uses elsewhere — a list of
# message dicts with ``role`` and ``content``. Kept as a type alias
# (not a fancier model) so we don't introduce a new shape just for
# this subsystem.
Transcript = list[dict[str, Any]]


@dataclass(frozen=True)
class ExtractedFact:
    """One fact pulled out of a transcript by the extraction LLM.

    ``id`` is a short slug used both as the markdown filename
    (``<id>.md``) and the stable handle for updates. ``confidence``
    is the extractor's self-rated certainty (0.0–1.0); the markdown
    backend stores it as frontmatter and lets the agent decide how
    much to trust the fact at query time.
    """

    id: str
    body: str
    category: str
    confidence: float


@dataclass(frozen=True)
class IngestResult:
    """Return value from ``ingest_session``. Counts and timing for
    diagnostics — fire-and-forget callers can ignore."""

    facts_added: int
    facts_updated: int
    duration_ms: int
    backend: str


@dataclass(frozen=True)
class QueryResult:
    """Return value from ``query``. ``answer`` is synthesized prose
    suitable to drop into a tool response. ``sources`` lists the
    fact IDs the answer drew on; the tool layer turns these into
    ``[auto]``/``[user]`` provenance tags so the agent can weight
    them. ``confidence`` is 0.0 when no source could be found,
    else 1.0 for the markdown backend (which has no embedding
    distance to expose); richer backends may interpolate."""

    answer: str
    sources: list[str]
    confidence: float


@dataclass(frozen=True)
class BackendHealth:
    """Cheap self-check, queried at startup and via diagnostics
    tools. ``status`` is one of ``ready`` / ``degraded`` / ``down``;
    ``reason`` is a short human string explaining the state."""

    status: str
    reason: str
    backend: str


@runtime_checkable
class UserModelBackend(Protocol):
    """Backend for auto-extracted observations about the user and
    their project. See ``athena/user_model/markdown.py`` for the
    default implementation."""

    async def ingest_session(
        self,
        transcript: Transcript,
        *,
        session_id: str,
    ) -> IngestResult:
        """Extract facts from a completed session.

        Idempotent on ``session_id`` — re-ingestion overwrites
        prior extraction for the same session. Callers that don't
        care about the result (fire-and-forget) may discard it;
        the return value exists for diagnostics and tests.
        """

    async def query(
        self,
        question: str,
        *,
        max_tokens: int = 800,
    ) -> QueryResult:
        """Natural-language recall over the stored facts."""

    def health(self) -> BackendHealth:
        """Synchronous self-check. Must not block on network for
        more than a few hundred milliseconds — used in startup
        paths and diagnostic tools."""
