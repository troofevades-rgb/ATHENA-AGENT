"""Pool eviction must skip refcount-pinned agents.

Surfaced by stress harness: 100 concurrent sessions × 3 platforms
with max_warm=50 produced constant churn — agents were evicted
mid-turn, the eviction closed their owned SessionStore, and the
in-flight ``Agent.run_until_done`` thread's next sqlite write
landed on a closed connection: "Cannot operate on a closed
database — JSONL is intact, run athena reindex to rebuild".
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from athena.gateway.agent_pool import AgentPool


class FakeAgent:
    """Tracks whether close() ran so the test can assert on it."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.closed = False

    def close(self) -> None:
        self.closed = True


async def _factory_for(session_id: str) -> FakeAgent:
    return FakeAgent(session_id)


async def test_pinned_agent_is_not_evicted_under_overflow() -> None:
    pool = AgentPool(_factory_for, max_size=2)

    async with pool.use("a") as agent_a:
        # `a` is pinned. Hit the pool with two more session_ids that
        # would normally LRU-evict it.
        async with pool.use("b") as agent_b:
            agent_c = await pool.get("c")

            # Pool size temporarily exceeds max_size because the
            # only eviction candidate (`a`) is pinned. That trade is
            # documented and correct: better to overshoot the cap
            # than close an in-flight agent.
            assert "a" in pool._cache
            assert "b" in pool._cache
            assert "c" in pool._cache
            assert agent_a.closed is False
            assert agent_b.closed is False

    # After `a` is released, the next overflow eviction can claim it.
    # Force one by spawning a fourth, unpinned entry.
    await pool.get("d")
    # Either `a` or `c` should now be gone (whichever was oldest);
    # the key point is that `a`'s close ran.
    assert agent_a.closed is True
    assert "a" not in pool._cache


async def test_unpinned_entries_evict_normally() -> None:
    """Sanity: the pin behavior must not regress normal LRU eviction
    of unpinned entries."""
    pool = AgentPool(_factory_for, max_size=2)
    agent_a = await pool.get("a")
    agent_b = await pool.get("b")
    agent_c = await pool.get("c")
    # `a` was the oldest unpinned entry, so it's the one that got
    # closed when `c` overflowed the cap.
    assert agent_a.closed is True
    assert agent_b.closed is False
    assert agent_c.closed is False


async def test_pin_is_refcount_not_boolean() -> None:
    """Concurrent uses of the same agent stack — eviction is gated
    until every use scope releases."""
    pool = AgentPool(_factory_for, max_size=1)
    async with pool.use("a") as agent_outer:
        async with pool.use("a") as agent_inner:
            # Force pool growth; `a` must survive both pins.
            await pool.get("b")
            assert "a" in pool._cache
            assert agent_outer.closed is False
            assert agent_inner.closed is False
        # Outer pin still held — eviction still blocked.
        await pool.get("c")
        assert "a" in pool._cache
        assert agent_outer.closed is False


async def test_pin_releases_after_exception_in_body() -> None:
    pool = AgentPool(_factory_for, max_size=1)
    with pytest.raises(RuntimeError, match="boom"):
        async with pool.use("a"):
            raise RuntimeError("boom")
    # Pin released, normal eviction now possible.
    assert pool._inflight.get("a", 0) == 0
