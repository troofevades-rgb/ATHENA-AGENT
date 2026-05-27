"""Cross-thread concurrency tests for ``GLOBAL_STEER_QUEUE``.

The existing ``test_queue.py`` covers single-thread happy-path
semantics. These add the real-world scenario: multiple producer
threads pushing concurrently while drain runs from another thread.
Phase 10 gateway adapters (Telegram, Slack, etc.) will push from
background reader threads, so this concurrency case is the actual
production path.

What we verify:

  * No message loss under concurrent push from N threads
  * Per-session FIFO order (cross-thread order is undefined,
    but per-producer order must be preserved)
  * Per-session isolation (push to session A doesn't appear
    in session B)
  * Drain during in-flight push doesn't corrupt the queue
  * No deadlocks under sustained load
  * push() never raises, even when called rapidly from many threads
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from athena.steer.queue import GLOBAL_STEER_QUEUE, SteerQueue


@pytest.fixture(autouse=True)
def _clean_queue():
    """Drop everything before AND after each test so concurrent runs
    don't bleed state."""
    for sid in list(GLOBAL_STEER_QUEUE._q.keys()):
        GLOBAL_STEER_QUEUE.clear(sid)
    yield
    for sid in list(GLOBAL_STEER_QUEUE._q.keys()):
        GLOBAL_STEER_QUEUE.clear(sid)


# ---------------------------------------------------------------------------
# Sustained push from many threads — no losses
# ---------------------------------------------------------------------------


def test_concurrent_push_loses_nothing_for_single_session() -> None:
    """N threads each push M messages into the same session. The
    final drain must contain exactly N*M messages — no duplicates,
    no losses."""
    sid = "stress-1"
    N_THREADS = 16
    M_PER_THREAD = 50

    def _producer(thread_id: int) -> None:
        for i in range(M_PER_THREAD):
            GLOBAL_STEER_QUEUE.push(sid, f"t{thread_id}-msg{i}")

    with ThreadPoolExecutor(max_workers=N_THREADS) as ex:
        list(ex.map(_producer, range(N_THREADS)))

    drained = GLOBAL_STEER_QUEUE.drain(sid)
    assert len(drained) == N_THREADS * M_PER_THREAD, (
        f"lost messages: expected {N_THREADS * M_PER_THREAD}, "
        f"got {len(drained)}"
    )
    # Every (thread, msg) pair appears exactly once
    expected = {
        f"t{t}-msg{i}" for t in range(N_THREADS) for i in range(M_PER_THREAD)
    }
    assert set(drained) == expected
    assert len(set(drained)) == len(drained), "duplicates in drained set"


def test_per_thread_fifo_order_preserved_under_concurrency() -> None:
    """Cross-thread order is undefined (threads race), but the
    relative order of messages from a SINGLE producing thread must
    be preserved. Test by tagging each msg with its sequence number
    and verifying per-thread monotonicity in the drained list."""
    sid = "fifo-1"
    N_THREADS = 8
    M_PER_THREAD = 100

    def _producer(thread_id: int) -> None:
        for i in range(M_PER_THREAD):
            GLOBAL_STEER_QUEUE.push(sid, f"{thread_id}:{i}")

    with ThreadPoolExecutor(max_workers=N_THREADS) as ex:
        list(ex.map(_producer, range(N_THREADS)))

    drained = GLOBAL_STEER_QUEUE.drain(sid)
    # Extract per-thread sequences
    per_thread: dict[int, list[int]] = {}
    for msg in drained:
        t_str, i_str = msg.split(":")
        per_thread.setdefault(int(t_str), []).append(int(i_str))

    for tid, seq in per_thread.items():
        assert seq == sorted(seq), (
            f"thread {tid}: sequence not monotonic ({seq[:10]}...). "
            f"FIFO violated for a single producer."
        )


# ---------------------------------------------------------------------------
# Cross-session isolation
# ---------------------------------------------------------------------------


def test_concurrent_pushes_to_different_sessions_do_not_mix() -> None:
    """Two producers push into different session IDs. Each drain
    must only return its own session's messages."""
    def _producer(sid: str, prefix: str, count: int) -> None:
        for i in range(count):
            GLOBAL_STEER_QUEUE.push(sid, f"{prefix}-{i}")

    threads = [
        threading.Thread(target=_producer, args=("alpha", "A", 100)),
        threading.Thread(target=_producer, args=("beta", "B", 100)),
        threading.Thread(target=_producer, args=("gamma", "G", 100)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    a = GLOBAL_STEER_QUEUE.drain("alpha")
    b = GLOBAL_STEER_QUEUE.drain("beta")
    g = GLOBAL_STEER_QUEUE.drain("gamma")

    assert all(m.startswith("A-") for m in a), f"alpha contaminated: {a[:5]}"
    assert all(m.startswith("B-") for m in b), f"beta contaminated: {b[:5]}"
    assert all(m.startswith("G-") for m in g), f"gamma contaminated: {g[:5]}"
    assert len(a) == 100 and len(b) == 100 and len(g) == 100


# ---------------------------------------------------------------------------
# Drain during in-flight push
# ---------------------------------------------------------------------------


def test_drain_during_concurrent_push_does_not_lose_or_duplicate() -> None:
    """Mimics the gateway-adapter scenario: while a producer is
    still pushing, the consumer (agent loop) drains. Subsequent
    pushes go into a fresh queue; previous + current must all
    arrive eventually without duplication."""
    sid = "race-1"
    N_PER_BATCH = 200
    stop = threading.Event()
    push_count = [0]

    def _producer() -> None:
        i = 0
        while not stop.is_set():
            GLOBAL_STEER_QUEUE.push(sid, f"m{i}")
            push_count[0] += 1
            i += 1
            if i >= N_PER_BATCH * 4:
                break

    producer = threading.Thread(target=_producer)
    producer.start()

    # Concurrent drains
    all_drained: list[str] = []
    for _ in range(4):
        time.sleep(0.005)  # let some pushes accumulate
        all_drained.extend(GLOBAL_STEER_QUEUE.drain(sid))

    producer.join(timeout=5.0)
    # Final drain to catch anything still pending
    all_drained.extend(GLOBAL_STEER_QUEUE.drain(sid))

    # Every push made it into SOME drain
    assert len(all_drained) == push_count[0], (
        f"push_count={push_count[0]}, drained={len(all_drained)} — "
        f"messages were lost OR duplicated"
    )
    assert len(set(all_drained)) == len(all_drained), (
        "duplicates in drained set"
    )


# ---------------------------------------------------------------------------
# Clear vs concurrent push
# ---------------------------------------------------------------------------


def test_clear_during_concurrent_push_is_consistent() -> None:
    """clear() and push() racing must leave the queue in a defined
    state — either empty (clear won) or partially-populated (push
    won the race). Crucially, no exceptions and no corruption."""
    sid = "clr-1"

    def _producer() -> None:
        for i in range(500):
            GLOBAL_STEER_QUEUE.push(sid, f"x{i}")

    def _clearer() -> None:
        for _ in range(20):
            GLOBAL_STEER_QUEUE.clear(sid)
            time.sleep(0.001)

    p = threading.Thread(target=_producer)
    c = threading.Thread(target=_clearer)
    p.start()
    c.start()
    p.join(timeout=5.0)
    c.join(timeout=5.0)

    # Queue must be in a SOME consistent state (list of strings).
    final = GLOBAL_STEER_QUEUE.list(sid)
    assert isinstance(final, list)
    assert all(isinstance(m, str) for m in final), (
        f"queue corruption: got non-string items: "
        f"{[m for m in final if not isinstance(m, str)][:3]}"
    )


# ---------------------------------------------------------------------------
# Stress / soak — no deadlocks
# ---------------------------------------------------------------------------


def test_sustained_push_drain_does_not_deadlock() -> None:
    """20 producers + 4 drainers, 2 seconds of sustained activity.
    The whole thing must complete without hanging."""
    sid = "soak-1"
    stop = threading.Event()
    seen: list[str] = []
    seen_lock = threading.Lock()

    def _producer() -> None:
        i = 0
        while not stop.is_set():
            GLOBAL_STEER_QUEUE.push(sid, f"p{i}")
            i += 1

    def _drainer() -> None:
        while not stop.is_set():
            batch = GLOBAL_STEER_QUEUE.drain(sid)
            if batch:
                with seen_lock:
                    seen.extend(batch)

    threads = [
        threading.Thread(target=_producer, daemon=True) for _ in range(20)
    ] + [
        threading.Thread(target=_drainer, daemon=True) for _ in range(4)
    ]
    for t in threads:
        t.start()
    time.sleep(2.0)
    stop.set()
    for t in threads:
        t.join(timeout=2.0)

    # Pull anything left
    seen.extend(GLOBAL_STEER_QUEUE.drain(sid))

    # No deadlock means we got here; the actual count varies by
    # scheduling but must be > 0
    assert len(seen) > 0, "no messages flowed at all during 2s soak"
    # All threads exited cleanly
    for t in threads:
        assert not t.is_alive(), f"thread {t.name} did not finish"


# ---------------------------------------------------------------------------
# Module-level singleton vs fresh instance — both must work
# ---------------------------------------------------------------------------


def test_fresh_instance_is_independent_from_global() -> None:
    """A fresh SteerQueue must not share state with the global one.
    Important for tests + future code that wants its own queue."""
    fresh = SteerQueue()
    GLOBAL_STEER_QUEUE.push("indep", "global-msg")
    fresh.push("indep", "fresh-msg")
    assert GLOBAL_STEER_QUEUE.drain("indep") == ["global-msg"]
    assert fresh.drain("indep") == ["fresh-msg"]
