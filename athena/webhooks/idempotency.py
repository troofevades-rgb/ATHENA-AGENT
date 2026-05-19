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

Implementation: in-memory dict; lazy expiry on every check (we
don't need an O(1) heap-based cleaner for the volume webhooks see).
A daemon restart wipes the cache — acceptable trade-off since the
TTL is short (default 10 minutes); worst case the user's webhook
source retries once after a restart and we fire twice. Persisting
the cache would mean SQLite + invalidation logic for marginal gain.
"""

from __future__ import annotations

import threading
import time

DEFAULT_TTL_SECONDS = 600.0  # 10 minutes


class IdempotencyCache:
    """In-memory ``(webhook_id, key) → expires_at`` map."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        self.ttl_seconds = ttl_seconds
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
            self._entries[pair] = now + self.ttl_seconds
            return True

    def _purge_expired_unlocked(self, now: float) -> None:
        """Drop entries past their TTL. Called inline on every
        check_and_record; the cache stays small so this is fine."""
        expired = [pair for pair, expires_at in self._entries.items() if expires_at < now]
        for pair in expired:
            self._entries.pop(pair, None)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
