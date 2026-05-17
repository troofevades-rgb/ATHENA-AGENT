"""LRU cache of warm :class:`~athena.agent.core.Agent` instances.

The gateway daemon keeps a bounded pool of agents in memory so the
common case — same chat keeps talking — doesn't pay the cost of
rehydrating the agent (loading conversation history, fetching the
Modelfile SYSTEM, rebuilding the system prompt, opening provider
clients) on every inbound message.

Eviction is strict-LRU; the oldest unused entry gets dropped when the
pool exceeds :attr:`max_size`. Eviction calls
:meth:`Agent.close` so any owned provider client closes cleanly.

The actual Agent constructor is injected via ``factory`` so the pool
can be unit-tested without spinning up a real provider. Phase 10.8
plugs in the real factory.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from ..agent.core import Agent

logger = logging.getLogger(__name__)


# Factory contract: ``async def make_agent(session_id) -> Agent``.
# The factory is responsible for instantiating an Agent bound to the
# given session_id (resuming history if the session pre-exists).
AgentFactory = Callable[[str], Awaitable["Agent"]]


class AgentPool:
    """Bounded LRU pool of agents keyed by ``session_id``.

    All public methods are async. The internal :class:`asyncio.Lock`
    serializes mutations so concurrent inbound messages can't race
    each other into instantiating two agents for the same session.
    """

    def __init__(
        self,
        factory: AgentFactory,
        *,
        max_size: int = 50,
    ) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._factory = factory
        self.max_size = max_size
        self._cache: OrderedDict[str, "Agent"] = OrderedDict()
        self._lock = asyncio.Lock()
        # Per-session instantiation locks so two simultaneous resolve()
        # calls for the same session_id don't both ask the factory.
        # Cleaned up after the agent lands in _cache.
        self._instantiation_locks: dict[str, asyncio.Lock] = {}

    async def get(self, session_id: str) -> "Agent":
        """Return the agent for ``session_id``, instantiating if absent.

        On a cache hit, the entry moves to the most-recently-used
        position. On a miss, the factory is awaited *outside* the
        pool-wide lock — agents can take seconds to instantiate
        (history loading + system-prompt build) and we don't want to
        block other sessions during that.
        """
        async with self._lock:
            if session_id in self._cache:
                self._cache.move_to_end(session_id)
                return self._cache[session_id]
            inst_lock = self._instantiation_locks.setdefault(
                session_id, asyncio.Lock()
            )

        async with inst_lock:
            # Re-check under the inst lock: another caller may have
            # finished instantiation while we were waiting.
            async with self._lock:
                if session_id in self._cache:
                    self._cache.move_to_end(session_id)
                    return self._cache[session_id]

            agent = await self._factory(session_id)

            async with self._lock:
                self._cache[session_id] = agent
                self._cache.move_to_end(session_id)
                self._instantiation_locks.pop(session_id, None)
                await self._evict_if_full_unlocked()

            return agent

    async def evict(self, session_id: str) -> bool:
        """Drop ``session_id`` from the pool. Returns True iff present.

        Calls :meth:`Agent.close` on the evicted instance so any owned
        provider client closes cleanly.
        """
        async with self._lock:
            agent = self._cache.pop(session_id, None)
        if agent is None:
            return False
        await self._close_agent(agent, session_id)
        return True

    async def evict_all(self) -> None:
        """Drop every entry. Used on daemon shutdown."""
        async with self._lock:
            entries = list(self._cache.items())
            self._cache.clear()
        for session_id, agent in entries:
            await self._close_agent(agent, session_id)

    async def _evict_if_full_unlocked(self) -> None:
        """Evict the oldest entry while over capacity. Caller holds
        ``self._lock`` — eviction itself takes that lock recursively
        through :meth:`evict`, which would deadlock, so close the
        agent directly here."""
        while len(self._cache) > self.max_size:
            session_id, agent = self._cache.popitem(last=False)
            # Release the lock for the close — close may do I/O.
            # We must release manually because we're in a 'while'
            # inside an 'async with self._lock' block.
            self._lock.release()
            try:
                await self._close_agent(agent, session_id)
            finally:
                await self._lock.acquire()

    async def _close_agent(self, agent: "Agent", session_id: str) -> None:
        try:
            close = getattr(agent, "close", None)
            if close is None:
                return
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception(
                "agent.close failed during eviction for %s", session_id
            )

    # ---- inspection ----

    @property
    def size(self) -> int:
        return len(self._cache)

    def contains(self, session_id: str) -> bool:
        return session_id in self._cache

    def session_ids(self) -> list[str]:
        """Return cached session ids in LRU order (oldest first)."""
        return list(self._cache.keys())
