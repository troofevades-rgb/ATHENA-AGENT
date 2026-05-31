"""TTL-scoped idempotency cache.

External webhook sources (GitHub, Linear, etc.) frequently retry on
network blips. Without idempotency, a slow handler can cause the
same payload to dispatch twice — once on the original POST, once
on the retry that arrived after we acked. Both fire the agent.

Mitigation: the sender supplies ``X-Webhook-Idempotency-Key``;
duplicates within :attr:`ttl_seconds` return 200 no-op'd without
firing the agent again.

Keyed by ``(webhook_id, key)`` — two different webhooks using the
same idempotency key value don't collide. Thread-safe via a single
mutex; the cache is small and contention is negligible.

Implementation: insertion-ordered dict so the oldest entry is at
the head; lazy expiry on every check; LRU-style eviction once the
cache hits :attr:`max_entries`. A daemon restart wipes the cache —
acceptable trade-off since the TTL is short (default 10 minutes);
worst case the user's webhook source retries once after a restart
and we fire twice. Persisting would mean SQLite + invalidation logic
for marginal gain.
"""

from __future__ import annotations

import threading
import time

DEFAULT_TTL_SECONDS = 600.0  # 10 minutes
# Hard upper bound so a misbehaving sender (or a hostile one) that
# pushes unique keys at 100 RPS for an hour can't grow the cache to
# 360k entries before TTL expiry catches up. At cap we evict the
# OLDEST entries first (insertion order = approximate LRU since
# every record is fresh at insert time). Sized for tens-of-thousands
# of distinct in-flight idempotency keys, well above any legitimate
# webhook load.
DEFAULT_MAX_ENTRIES = 50_000


class IdempotencyCache:
    """In-memory ``(webhook_id, key) → expires_at`` map."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def check_and_record(self, webhook_id: str, key: str) -> bool:
        """Atomically check the (webhook_id, key) pair.

        Returns True iff this is the *first* time we've seen the pair
        (so the caller should dispatch). Returns False if it's a
        duplicate within :attr:`ttl_seconds` (caller should 200
        no-op).

        Empty key short-circuits to True without recording — a
        webhook source that doesn't supply the header gets no
        idempotency protection. (We could record empty keys but
        then the second un-keyed call would falsely dedupe; better
        to be a no-op when the sender opts out.)
        """
        if not key:
            return True
        now = time.monotonic()
        pair = (webhook_id, key)
        with self._lock:
            self._purge_expired_unlocked(now)
            if pair in self._entries:
                return False
            # LRU-style cap: if we're still at the limit after the
            # TTL purge, evict the oldest entry. dict iteration order
            # is insertion order in CPython 3.7+, so the first key
            # is the oldest live entry.
            while len(self._entries) >= self.max_entries:
                oldest = next(iter(self._entries))
                self._entries.pop(oldest, None)
            self._entries[pair] = now + self.ttl_seconds
            return True

    def _purge_expired_unlocked(self, now: float) -> None:
        """Drop entries past their TTL. Called inline on every
        check_and_record; the cache stays small so this is fine.

        Uses ``<=`` (not ``<``) so an entry expiring at exactly
        ``now`` gets dropped on this pass instead of surviving to
        falsely-dedupe the next call. The 1-tick window is real
        on coarse-clock platforms (Windows monotonic resolution
        can be ~15ms) and the previous strict-less-than allowed a
        legitimate retry to silently 200 no-op."""
        expired = [pair for pair, expires_at in self._entries.items() if expires_at <= now]
        for pair in expired:
            self._entries.pop(pair, None)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
