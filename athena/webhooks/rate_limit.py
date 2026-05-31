"""Per-webhook sliding-window rate limiter.

Each webhook has its own counter. Implementation: a deque of
timestamps per id; on every check, drop entries older than 60s
and compare the remaining count against the limit.

In-memory; resets on daemon restart. That's acceptable — a webhook
source that bursts past the limit during a restart window gets
back-to-back fires for ~60 seconds, after which the limiter kicks
back in. Persisting would mean SQLite + transaction overhead per
check for marginal benefit.
"""

from __future__ import annotations

import threading
import time
from collections import deque

_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Per-id sliding-window rate limiter."""

    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, webhook_id: str, per_minute: int) -> bool:
        """Return True iff this call fits inside the per-minute budget.

        Records the timestamp on success; doesn't record on failure
        (so a sustained over-budget source can't spike the deque to
        infinity).
        """
        if per_minute < 1:
            return False
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        with self._lock:
            bucket = self._buckets.setdefault(webhook_id, deque())
            # Drop expired entries from the left.
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= per_minute:
                return False
            bucket.append(now)
            return True

    def reset(self, webhook_id: str | None = None) -> None:
        """Test helper / admin: clear one bucket or all."""
        with self._lock:
            if webhook_id is None:
                self._buckets.clear()
            else:
                self._buckets.pop(webhook_id, None)

    def current_count(self, webhook_id: str) -> int:
        """For diagnostics / status output. Read-only -- does NOT
        mutate the bucket.

        The previous implementation called ``bucket.popleft()`` to
        drop expired entries before returning the count. That had
        the side effect of permanently dropping timestamps a
        concurrent ``check()`` may still have needed (e.g., a /status
        call mid-burst could under-count the next ``check()``'s view
        of the bucket). Diagnostics must never alter the limiter's
        observable behavior. The cost: we walk the bucket once per
        call instead of popping in place; bucket sizes are bounded
        by ``per_minute`` so this is O(per_minute) and cheap."""
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        with self._lock:
            bucket = self._buckets.get(webhook_id)
            if bucket is None:
                return 0
            return sum(1 for ts in bucket if ts >= cutoff)
