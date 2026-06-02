"""RateLimiter — per-webhook sliding-window rate limiter.

Confirms the limiter's core semantics (per-id budget, sliding window
expiry, thread safety) plus the read-only ``current_count``
invariant (no observable side effect on the limiter when /status
queries the bucket mid-burst — the pre-fix behavior popped entries
during ``current_count`` and could cause a concurrent ``check()``
to under-count.)
"""

from __future__ import annotations

import threading
import time

from athena.webhooks.rate_limit import RateLimiter


def test_check_under_budget_returns_true() -> None:
    rl = RateLimiter()
    for _ in range(3):
        assert rl.check("w", per_minute=10) is True


def test_check_over_budget_returns_false() -> None:
    rl = RateLimiter()
    for _ in range(5):
        rl.check("w", per_minute=5)
    # Sixth call inside the window is rejected.
    assert rl.check("w", per_minute=5) is False


def test_check_rejects_zero_or_negative_limit() -> None:
    rl = RateLimiter()
    assert rl.check("w", per_minute=0) is False
    assert rl.check("w", per_minute=-1) is False


def test_check_per_id_independent() -> None:
    """Two webhooks have independent buckets."""
    rl = RateLimiter()
    for _ in range(5):
        rl.check("a", per_minute=5)
    # 'a' is at limit but 'b' is fresh.
    assert rl.check("a", per_minute=5) is False
    assert rl.check("b", per_minute=5) is True


def test_check_does_not_record_when_rejected() -> None:
    """A sustained over-budget source can't spike the deque to
    infinity -- rejected calls do NOT append a timestamp."""
    rl = RateLimiter()
    for _ in range(5):
        rl.check("w", per_minute=5)
    # All these calls are rejected; the bucket stays at 5.
    for _ in range(100):
        rl.check("w", per_minute=5)
    assert rl.current_count("w") == 5


def test_reset_clears_one_bucket() -> None:
    rl = RateLimiter()
    rl.check("a", per_minute=10)
    rl.check("b", per_minute=10)
    rl.reset("a")
    assert rl.current_count("a") == 0
    assert rl.current_count("b") == 1


def test_reset_clears_all_buckets() -> None:
    rl = RateLimiter()
    rl.check("a", per_minute=10)
    rl.check("b", per_minute=10)
    rl.reset()
    assert rl.current_count("a") == 0
    assert rl.current_count("b") == 0


# ---- read-only current_count (review finding #6) -------------------


def test_current_count_does_not_mutate_bucket() -> None:
    """The pre-fix implementation called ``bucket.popleft()`` during
    ``current_count`` to drop expired entries. That had the side
    effect of permanently dropping timestamps a concurrent
    ``check()`` may still have needed (status endpoint could
    under-count the next check's view of the bucket).

    Post-fix: current_count must be a pure read. Even after the
    window expires, the bucket itself stays intact -- only the
    next ``check()`` mutates the deque."""
    rl = RateLimiter()
    rl.check("w", per_minute=10)
    rl.check("w", per_minute=10)
    rl.check("w", per_minute=10)
    # Inspect the underlying bucket directly to confirm no mutation.
    with rl._lock:
        bucket_before = list(rl._buckets["w"])
    # Call current_count many times.
    for _ in range(50):
        rl.current_count("w")
    with rl._lock:
        bucket_after = list(rl._buckets["w"])
    assert bucket_before == bucket_after


def test_current_count_filters_expired_entries_without_dropping(
    monkeypatch,
) -> None:
    """An expired entry should NOT count toward the diagnostic
    total, but it should remain in the deque until ``check()``
    actually rotates it out."""
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    rl = RateLimiter()
    rl.check("w", per_minute=10)  # t=1000
    rl.check("w", per_minute=10)  # t=1000
    assert rl.current_count("w") == 2
    # Advance past the 60s window.
    clock[0] = 1070.0
    assert rl.current_count("w") == 0
    # Bucket is still untouched (current_count didn't mutate it).
    with rl._lock:
        assert len(rl._buckets["w"]) == 2


def test_current_count_returns_zero_for_unknown_id() -> None:
    rl = RateLimiter()
    assert rl.current_count("never-seen") == 0


# ---- concurrency ---------------------------------------------------


def test_check_thread_safe_under_burst() -> None:
    """100 threads racing on the same webhook against a per_minute=10
    budget: exactly 10 pass, the rest are rejected."""
    rl = RateLimiter()
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = rl.check("w", per_minute=10)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 10
    assert results.count(False) == 90
