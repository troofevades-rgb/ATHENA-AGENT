"""IdempotencyCache — TTL-scoped duplicate-key detection."""

from __future__ import annotations

import threading
import time

import pytest

from athena.webhooks.idempotency import IdempotencyCache


def test_first_call_returns_true() -> None:
    cache = IdempotencyCache(ttl_seconds=60)
    assert cache.check_and_record("webhook-1", "delivery-1") is True


def test_duplicate_returns_false() -> None:
    cache = IdempotencyCache(ttl_seconds=60)
    cache.check_and_record("webhook-1", "delivery-1")
    assert cache.check_and_record("webhook-1", "delivery-1") is False


def test_different_webhook_same_key_not_dedup() -> None:
    cache = IdempotencyCache(ttl_seconds=60)
    cache.check_and_record("webhook-1", "abc")
    # Same key on a DIFFERENT webhook — must dispatch independently.
    assert cache.check_and_record("webhook-2", "abc") is True


def test_different_key_same_webhook_not_dedup() -> None:
    cache = IdempotencyCache(ttl_seconds=60)
    cache.check_and_record("w", "a")
    assert cache.check_and_record("w", "b") is True


def test_empty_key_always_returns_true() -> None:
    """No idempotency header → no idempotency protection. First call
    and a duplicate both succeed."""
    cache = IdempotencyCache(ttl_seconds=60)
    assert cache.check_and_record("w", "") is True
    assert cache.check_and_record("w", "") is True


def test_ttl_expiry_allows_again() -> None:
    """After ttl_seconds, a previously-seen key gets recorded again."""
    cache = IdempotencyCache(ttl_seconds=0.05)
    cache.check_and_record("w", "k")
    assert cache.check_and_record("w", "k") is False
    # Generous margin (3× TTL) so a busy CI machine doesn't make
    # this flake. time.monotonic granularity + scheduler jitter
    # eats well under 100ms even under load.
    time.sleep(0.2)
    assert cache.check_and_record("w", "k") is True


def test_size_reflects_recorded_entries() -> None:
    cache = IdempotencyCache(ttl_seconds=60)
    assert cache.size == 0
    cache.check_and_record("w", "a")
    cache.check_and_record("w", "b")
    assert cache.size == 2


def test_clear_drops_everything() -> None:
    cache = IdempotencyCache(ttl_seconds=60)
    cache.check_and_record("w", "a")
    cache.check_and_record("w", "b")
    cache.clear()
    assert cache.size == 0
    # Previously-recorded key can be recorded again.
    assert cache.check_and_record("w", "a") is True


def test_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError):
        IdempotencyCache(ttl_seconds=0)
    with pytest.raises(ValueError):
        IdempotencyCache(ttl_seconds=-1)


# ---- concurrency --------------------------------------------------


def test_thread_safe_under_contention() -> None:
    """100 threads racing on the same (webhook_id, key) — exactly
    one wins (returns True); the rest see False."""
    cache = IdempotencyCache(ttl_seconds=60)
    wins: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        result = cache.check_and_record("w", "race")
        with lock:
            wins.append(result)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Exactly one True; the other 99 are False.
    assert wins.count(True) == 1
    assert wins.count(False) == 99


def test_lazy_expiry_cleans_old_entries() -> None:
    """After TTL passes and another check runs, the expired entry
    gets purged — verified by size dropping."""
    cache = IdempotencyCache(ttl_seconds=0.03)
    cache.check_and_record("w", "a")
    assert cache.size == 1
    time.sleep(0.15)  # 5× TTL — generous CI margin
    # Trigger a check that runs the lazy purge.
    cache.check_and_record("w", "b")
    # 'a' was purged; only 'b' remains.
    assert cache.size == 1


# ---- bounded growth (LRU cap) --------------------------------------


def test_max_entries_caps_dict_growth() -> None:
    """A misbehaving sender pushing unique keys cannot grow the
    cache past ``max_entries``. Oldest entries get evicted first
    (insertion order in CPython 3.7+ = approximate LRU since every
    insert is fresh)."""
    cache = IdempotencyCache(ttl_seconds=60, max_entries=3)
    cache.check_and_record("w", "a")
    cache.check_and_record("w", "b")
    cache.check_and_record("w", "c")
    assert cache.size == 3
    # Fourth insert -- must evict the oldest ("a") to stay at 3.
    cache.check_and_record("w", "d")
    assert cache.size == 3
    # 'a' was evicted and can be recorded again as new.
    assert cache.check_and_record("w", "a") is True
    # 'd' still in cache and is treated as duplicate.
    assert cache.check_and_record("w", "d") is False


def test_max_entries_must_be_positive() -> None:
    with pytest.raises(ValueError):
        IdempotencyCache(ttl_seconds=60, max_entries=0)
    with pytest.raises(ValueError):
        IdempotencyCache(ttl_seconds=60, max_entries=-1)


# ---- TTL boundary (the <= fix from review finding #3) -------------


def test_entry_expiring_exactly_at_now_does_not_dedup_next_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 1-tick TTL boundary bug: previously the purge used strict
    ``<`` so an entry whose expiry equalled the new check's ``now``
    would survive purge and then dedupe the legitimate retry. On
    Windows ``time.monotonic`` resolution is ~15ms so this isn't
    purely theoretical -- two calls inside the same tick collide.

    Pin with a controlled clock so the boundary is exact."""
    clock = [1000.0]

    def fake_monotonic() -> float:
        return clock[0]

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    cache = IdempotencyCache(ttl_seconds=10)
    # Record at t=1000; expires at t=1010.
    assert cache.check_and_record("w", "k") is True
    # Advance the clock to EXACTLY the expiry moment.
    clock[0] = 1010.0
    # Post-fix: the entry must NOT dedupe a fresh call -- it has
    # expired (now >= expires_at means the entry's lifetime is over).
    assert cache.check_and_record("w", "k") is True
