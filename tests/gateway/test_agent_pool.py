"""AgentPool — bounded LRU pool of warm agents.

Uses a fake agent factory so the pool's LRU + concurrency contract can
be exercised without spinning up a real Agent / Provider.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from athena.gateway.agent_pool import AgentPool


@dataclass
class _FakeAgent:
    session_id: str
    closed: bool = False
    close_calls: int = field(default=0)

    async def close(self) -> None:
        self.closed = True
        self.close_calls += 1


def _factory(*, delay: float = 0.0, agents: dict[str, _FakeAgent] | None = None):
    agents = agents if agents is not None else {}
    call_log: list[str] = []

    async def make(session_id: str) -> _FakeAgent:
        call_log.append(session_id)
        if delay:
            await asyncio.sleep(delay)
        agent = _FakeAgent(session_id=session_id)
        agents[session_id] = agent
        return agent

    make.call_log = call_log  # type: ignore[attr-defined]
    make.agents = agents  # type: ignore[attr-defined]
    return make


# ---- basic get ---------------------------------------------------------


async def test_get_creates_agent_first_time() -> None:
    pool = AgentPool(_factory(), max_size=4)
    agent = await pool.get("sess-1")
    assert isinstance(agent, _FakeAgent)
    assert agent.session_id == "sess-1"
    assert pool.size == 1


async def test_get_returns_cached_agent_on_second_call() -> None:
    factory = _factory()
    pool = AgentPool(factory, max_size=4)
    a1 = await pool.get("sess-1")
    a2 = await pool.get("sess-1")
    assert a1 is a2
    assert factory.call_log == ["sess-1"]


async def test_max_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AgentPool(_factory(), max_size=0)


# ---- LRU semantics ----------------------------------------------------


async def test_oldest_evicted_when_pool_full() -> None:
    factory = _factory()
    pool = AgentPool(factory, max_size=2)
    a1 = await pool.get("s1")
    await pool.get("s2")
    await pool.get("s3")  # forces eviction of s1

    assert pool.size == 2
    assert not pool.contains("s1")
    assert pool.contains("s2") and pool.contains("s3")
    assert a1.closed, "evicted agent must have close() called"


async def test_get_moves_entry_to_most_recently_used() -> None:
    pool = AgentPool(_factory(), max_size=2)
    a1 = await pool.get("s1")
    await pool.get("s2")
    # Touch s1 — s2 becomes the LRU.
    await pool.get("s1")
    # Add s3 → s2 evicts, s1 survives.
    await pool.get("s3")
    assert pool.contains("s1")
    assert not pool.contains("s2")
    assert not a1.closed


async def test_eviction_does_not_re_evict_already_evicted() -> None:
    factory = _factory()
    pool = AgentPool(factory, max_size=1)
    a1 = await pool.get("s1")
    await pool.get("s2")  # evicts s1
    assert a1.close_calls == 1
    await pool.get("s3")  # evicts s2; a1 must not be touched again
    assert a1.close_calls == 1


# ---- explicit evict ---------------------------------------------------


async def test_evict_removes_entry_and_closes_agent() -> None:
    pool = AgentPool(_factory(), max_size=4)
    agent = await pool.get("s1")
    assert await pool.evict("s1") is True
    assert agent.closed
    assert pool.size == 0


async def test_evict_returns_false_for_missing_session() -> None:
    pool = AgentPool(_factory(), max_size=4)
    assert await pool.evict("never-existed") is False


async def test_evict_all_drains_every_entry() -> None:
    factory = _factory()
    pool = AgentPool(factory, max_size=4)
    await pool.get("s1")
    await pool.get("s2")
    await pool.get("s3")
    await pool.evict_all()
    assert pool.size == 0
    for agent in factory.agents.values():
        assert agent.closed


async def test_close_exceptions_are_swallowed() -> None:
    """A misbehaving close() must not break eviction for other sessions."""
    factory = _factory()
    pool = AgentPool(factory, max_size=1)
    a1 = await pool.get("s1")

    async def boom() -> None:
        raise RuntimeError("boom")

    a1.close = boom  # type: ignore[method-assign]
    # The eviction triggered by adding s2 must still succeed.
    await pool.get("s2")
    assert pool.contains("s2") and not pool.contains("s1")


# ---- concurrency / single-instantiation ------------------------------


async def test_concurrent_get_same_session_instantiates_once() -> None:
    factory = _factory(delay=0.02)
    pool = AgentPool(factory, max_size=4)
    agents = await asyncio.gather(
        pool.get("s1"),
        pool.get("s1"),
        pool.get("s1"),
    )
    assert agents[0] is agents[1] is agents[2]
    assert factory.call_log == ["s1"], "factory must be called exactly once for racing get('s1')"


async def test_concurrent_get_different_sessions_runs_in_parallel() -> None:
    """Slow factory + concurrent get() on distinct sessions must
    overlap, not serialize. We measure wall time to confirm."""
    factory = _factory(delay=0.05)
    pool = AgentPool(factory, max_size=4)
    import time

    start = time.monotonic()
    await asyncio.gather(pool.get("a"), pool.get("b"), pool.get("c"))
    elapsed = time.monotonic() - start
    # Serial would be ~0.15s; parallel should be ~0.05s. Allow slack.
    assert elapsed < 0.12, f"factory calls didn't parallelize (elapsed={elapsed:.3f}s)"


# ---- session_ids / introspection -------------------------------------


async def test_session_ids_returns_lru_order_oldest_first() -> None:
    pool = AgentPool(_factory(), max_size=4)
    await pool.get("s1")
    await pool.get("s2")
    await pool.get("s3")
    await pool.get("s2")  # touch s2 → newest
    assert pool.session_ids() == ["s1", "s3", "s2"]


# ---- factory hook -----------------------------------------------------


async def test_factory_receives_session_id() -> None:
    received: list[str] = []

    async def make(session_id: str):
        received.append(session_id)
        return _FakeAgent(session_id=session_id)

    pool = AgentPool(make, max_size=4)
    await pool.get("abc")
    await pool.get("xyz")
    assert received == ["abc", "xyz"]


async def test_factory_failure_does_not_install_phantom_entry() -> None:
    """If the factory raises, the pool must not record a half-baked
    entry — the next call must retry instantiation."""
    attempts: list[str] = []

    async def make(session_id: str):
        attempts.append(session_id)
        if len(attempts) == 1:
            raise RuntimeError("transient")
        return _FakeAgent(session_id=session_id)

    pool = AgentPool(make, max_size=4)
    with pytest.raises(RuntimeError):
        await pool.get("s1")
    assert not pool.contains("s1")
    a = await pool.get("s1")
    assert a.session_id == "s1"
    assert attempts == ["s1", "s1"]
