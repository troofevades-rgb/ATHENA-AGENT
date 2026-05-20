"""Cross-session prompt caching (T5-06).

T2-01 brought per-session prompt caching — `cache_control`
markers in the request, replayed on the same session's
follow-up turns. T5-06 extends that across sessions: a stable
prefix (system prompt + pinned skill bodies + durable project
context) cached in one session is reused in the next.

Two surfaces:

- :class:`CrossSessionCache` — content-hash keyed lookup +
  record + caching-plan resolution over the T5-01 manifest.
- :func:`prefix_hash` — SHA-256 of the exact prefix bytes. A
  changed prefix is a different key, never a wrong hit.
"""

from .cross_session import (
    CacheEntry,
    CachingPlan,
    CrossSessionCache,
    prefix_hash,
)

__all__ = [
    "CacheEntry",
    "CachingPlan",
    "CrossSessionCache",
    "prefix_hash",
]
