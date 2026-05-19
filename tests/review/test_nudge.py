"""Tests for the per-turn review nudge counter."""

from __future__ import annotations

import threading

import pytest

from athena.review import nudge


@pytest.fixture(autouse=True)
def _clean_state():
    nudge.reset_all()
    yield
    nudge.reset_all()


def test_counter_starts_at_zero() -> None:
    assert nudge.value("brand-new") == 0


def test_counter_increments() -> None:
    nudge.increment_and_check("s", 10)
    nudge.increment_and_check("s", 10)
    nudge.increment_and_check("s", 10)
    assert nudge.value("s") == 3


def test_fires_at_nudge_interval_multiple() -> None:
    fired = [nudge.increment_and_check("s", 5) for _ in range(15)]
    # Only ticks 5, 10, 15 fire.
    fire_indices = [i for i, f in enumerate(fired, start=1) if f]
    assert fire_indices == [5, 10, 15]


def test_does_not_fire_between_intervals() -> None:
    fired = [nudge.increment_and_check("s", 3) for _ in range(2)]
    assert not any(fired)


def test_per_session_isolation() -> None:
    # Two sessions advance independently.
    for _ in range(9):
        nudge.increment_and_check("a", 10)
    assert nudge.value("a") == 9
    assert nudge.value("b") == 0
    # b's tenth tick fires; a is still at 9.
    nudge.increment_and_check("b", 10)
    assert nudge.value("b") == 1


def test_none_session_never_fires() -> None:
    """An agent without a session_id (profile='') must be a no-op."""
    assert nudge.increment_and_check(None, 1) is False


def test_zero_interval_never_fires() -> None:
    assert nudge.increment_and_check("s", 0) is False


def test_reset_drops_counter() -> None:
    for _ in range(5):
        nudge.increment_and_check("s", 100)
    assert nudge.value("s") == 5
    nudge.reset("s")
    assert nudge.value("s") == 0


def test_concurrent_increments_are_serialized() -> None:
    """The module's internal lock keeps the counter consistent under parallel
    increments — concurrent fires would create double-counting otherwise."""
    iterations = 200
    threads_n = 8

    def _worker() -> None:
        for _ in range(iterations):
            nudge.increment_and_check("shared", 99999)

    threads = [threading.Thread(target=_worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert nudge.value("shared") == iterations * threads_n
