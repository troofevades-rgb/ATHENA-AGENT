"""SteerQueue: FIFO, per-session isolation, thread-safety."""

from __future__ import annotations

import threading

import pytest

from athena.steer.queue import GLOBAL_STEER_QUEUE, SteerQueue


@pytest.fixture
def queue() -> SteerQueue:
    return SteerQueue()


def test_push_and_pop_in_order(queue: SteerQueue):
    queue.push("s1", "first")
    queue.push("s1", "second")
    queue.push("s1", "third")
    assert queue.pop("s1") == "first"
    assert queue.pop("s1") == "second"
    assert queue.pop("s1") == "third"
    assert queue.pop("s1") is None


def test_pop_returns_none_when_empty(queue: SteerQueue):
    assert queue.pop("never_touched") is None


def test_drain_returns_all_in_order_and_empties(queue: SteerQueue):
    queue.push("s1", "a")
    queue.push("s1", "b")
    queue.push("s1", "c")
    assert queue.drain("s1") == ["a", "b", "c"]
    assert queue.drain("s1") == []  # idempotent


def test_list_does_not_remove(queue: SteerQueue):
    queue.push("s1", "x")
    queue.push("s1", "y")
    assert queue.list("s1") == ["x", "y"]
    # Still present:
    assert queue.list("s1") == ["x", "y"]


def test_clear_returns_count(queue: SteerQueue):
    queue.push("s1", "a")
    queue.push("s1", "b")
    queue.push("s1", "c")
    assert queue.clear("s1") == 3
    assert queue.clear("s1") == 0  # idempotent


def test_per_session_isolation(queue: SteerQueue):
    queue.push("s1", "for-s1")
    queue.push("s2", "for-s2")
    assert queue.pop("s1") == "for-s1"
    assert queue.pop("s1") is None
    # s2 unaffected by s1's pop:
    assert queue.list("s2") == ["for-s2"]


def test_thread_safe_concurrent_push(queue: SteerQueue):
    """Concurrent pushes from many threads must not lose any messages."""
    n_threads = 20
    per_thread = 50

    def worker(tid: int):
        for i in range(per_thread):
            queue.push("shared", f"t{tid}-i{i}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    drained = queue.drain("shared")
    assert len(drained) == n_threads * per_thread


def test_global_singleton_exists():
    """A module-level singleton must be importable for cross-thread use."""
    assert isinstance(GLOBAL_STEER_QUEUE, SteerQueue)
    # Use a session_id unique to this test so we don't trip on residue:
    GLOBAL_STEER_QUEUE.push("test-singleton", "hello")
    assert GLOBAL_STEER_QUEUE.pop("test-singleton") == "hello"
