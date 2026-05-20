"""Cross-session prompt cache: SHA-256-keyed prefix reuse (T5-06.1).

The single failure mode that matters is a wrong cache hit — serving
a stale prefix as if it were the current one. The defence is a
content-hash key: a changed prefix produces a different key and
can't match an old entry. TTL bounds staleness; the hash bounds
correctness.

Cached scope: the stable prefix only.

  system prompt + pinned skill bodies + durable project / memory
  context

Never cached: the conversation tail, tool results, recent turns —
anything that changes with the dialogue. The boundary is
conservative — when in doubt, treat as volatile.

Mechanism routing is manifest-driven (T5-01):

  prompt_caching=True + cache_ttls_seconds   → server-side cache
                                              (largest declared TTL)
  kv_cache_reuse=True                        → local KV reuse hook
                                              (the backend does the
                                              actual reuse — athena
                                              just keeps the prefix
                                              byte-stable + signals)
  neither                                    → no caching

Invalidation: automatic via hash change. Edit a skill / system
prompt / memory file → next session's prefix hashes differently →
the old entry simply doesn't match (and TTL-expires). A manual
``athena cache clear`` is available for the paranoid.

Tiny prefixes (below ``cache_min_prefix_tokens``) skip caching
entirely — the bookkeeping cost outweighs the benefit.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def prefix_hash(prefix_text: str) -> str:
    """SHA-256 of the prefix bytes. Hex digest. Deterministic +
    collision-resistant; identical inputs → identical hash;
    a single-character change → a completely different hash."""
    return hashlib.sha256(prefix_text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CacheEntry:
    """One cached prefix metadata record.

    The cached PAYLOAD is NOT stored here — for server-side cache,
    the provider owns it; for KV reuse, the local inference backend
    owns it. This entry is the index: "this hash, in this workspace,
    for this provider, was cached at time T with TTL S".
    """

    workspace: str
    prefix_hash: str
    provider: str
    provider_cache_id: str | None
    ttl_s: int
    created_at: float

    def alive(self, *, now: float | None = None) -> bool:
        """``True`` iff the entry hasn't TTL-expired. ``now`` is
        injectable for deterministic tests."""
        t = time.time() if now is None else now
        return (t - self.created_at) < self.ttl_s

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CacheEntry:
        return cls(**d)


# ---------------------------------------------------------------------------
# Caching plan — manifest lookup result
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CachingPlan:
    """How to cache for a given provider, derived from its T5-01
    capability manifest.

    ``mode`` is one of:
      ``"server"``   — provider supports server-side prompt caching;
                       use ``ttl_s`` as the declared TTL.
      ``"kv_reuse"`` — provider is local with kv_cache_reuse; the
                       backend does the actual reuse, athena keeps
                       the prefix byte-stable.
      ``"none"``     — no caching mechanism available for this
                       provider; send normally.
    """

    mode: str
    ttl_s: int | None = None


# ---------------------------------------------------------------------------
# CrossSessionCache
# ---------------------------------------------------------------------------


class CrossSessionCache:
    """Cross-session prefix-cache index.

    On-disk shape: a single JSON file at ``cfg.cache_index_path`` (or
    the constructor's ``index_path``), mapping
    ``"<workspace>::<hash>::<provider>"`` → :class:`CacheEntry`.

    Operations:

      :meth:`caching_plan(provider_name)` — pure manifest lookup
      :meth:`lookup(...)`                 — alive cache entry or None
      :meth:`record(...)`                 — store an entry; persists
      :meth:`clear()`                     — empty the index
    """

    def __init__(self, *, index_path: Path, cfg: Any):
        self.index_path = Path(index_path)
        self.cfg = cfg
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, CacheEntry] = self._load()

    # ------------------------------------------------------------------
    # Key
    # ------------------------------------------------------------------

    @staticmethod
    def _key(workspace: str, h: str, provider: str) -> str:
        return f"{workspace}::{h}::{provider}"

    # ------------------------------------------------------------------
    # Plan resolution (manifest-driven)
    # ------------------------------------------------------------------

    def caching_plan(self, provider_name: str) -> CachingPlan:
        """Ask the T5-01 manifest HOW to cache for this provider.

        Pure capability lookup — no instances, no network. Used at
        session start to decide whether to bother computing the
        prefix hash + consulting the index.
        """
        from ..providers import _REGISTRY

        cls = _REGISTRY.get(provider_name)
        if cls is None:
            return CachingPlan(mode="none")
        caps = cls.static_capabilities()
        if caps.prompt_caching and caps.cache_ttls_seconds:
            return CachingPlan(
                mode="server",
                ttl_s=max(caps.cache_ttls_seconds),
            )
        if caps.kv_cache_reuse:
            return CachingPlan(mode="kv_reuse")
        return CachingPlan(mode="none")

    # ------------------------------------------------------------------
    # Lookup / record / clear
    # ------------------------------------------------------------------

    def lookup(
        self,
        *,
        workspace: str,
        prefix_text: str,
        provider: str,
    ) -> CacheEntry | None:
        """Return an alive :class:`CacheEntry` for this (workspace,
        prefix, provider) tuple, or None.

        Tiny prefixes (below ``cfg.cache_min_prefix_tokens``) always
        miss — the index isn't consulted at all, mirroring
        :meth:`record`'s skip rule so the two surfaces agree."""
        if not self._should_cache(prefix_text):
            return None
        h = prefix_hash(prefix_text)
        entry = self._index.get(self._key(workspace, h, provider))
        if entry is None:
            return None
        if not entry.alive():
            logger.debug(
                "cache lookup expired for %s/%s/%s",
                workspace,
                h[:12],
                provider,
            )
            return None
        return entry

    def record(
        self,
        *,
        workspace: str,
        prefix_text: str,
        provider: str,
        provider_cache_id: str | None,
        ttl_s: int,
    ) -> CacheEntry | None:
        """Stash a fresh cache entry. Returns the entry (or None
        when ``prefix_text`` is too small to cache).

        Persists synchronously — cross-session reuse demands the
        write is durable before the calling session ends.
        """
        if not self._should_cache(prefix_text):
            logger.debug(
                "cache record skipped: prefix below cache_min_prefix_tokens"
            )
            return None
        entry = CacheEntry(
            workspace=workspace,
            prefix_hash=prefix_hash(prefix_text),
            provider=provider,
            provider_cache_id=provider_cache_id,
            ttl_s=int(ttl_s),
            created_at=time.time(),
        )
        self._index[self._key(workspace, entry.prefix_hash, provider)] = entry
        self._save()
        return entry

    def clear(self) -> int:
        """Empty the index. Returns the number of entries dropped."""
        count = len(self._index)
        self._index.clear()
        self._save()
        return count

    def all(self) -> list[CacheEntry]:
        """Every entry, sorted by created_at descending — for the
        ``athena cache status`` admin surface."""
        return sorted(
            self._index.values(),
            key=lambda e: e.created_at,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Token-count gate
    # ------------------------------------------------------------------

    def _should_cache(self, prefix_text: str) -> bool:
        """Heuristic gate: prefixes below the minimum token estimate
        skip caching entirely. The estimate is a cheap 4-bytes-per-
        token approximation — good enough for the "tiny vs not"
        decision without paying for a real tokenizer."""
        min_tokens = int(getattr(self.cfg, "cache_min_prefix_tokens", 1024))
        if min_tokens <= 0:
            return True
        estimated = len(prefix_text.encode("utf-8")) // 4
        return estimated >= min_tokens

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, CacheEntry]:
        if not self.index_path.exists():
            return {}
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("cache index unreadable, starting fresh: %s", e)
            return {}
        out: dict[str, CacheEntry] = {}
        for key, payload in raw.items():
            try:
                out[key] = CacheEntry.from_dict(payload)
            except (TypeError, KeyError) as e:
                logger.warning("skipping malformed cache entry %s: %s", key, e)
        return out

    def _save(self) -> None:
        payload = {k: e.to_dict() for k, e in self._index.items()}
        self.index_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
