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
import contextlib
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

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
        self._cache: OrderedDict[str, Agent] = OrderedDict()
        self._lock = asyncio.Lock()
        # Per-session instantiation locks so two simultaneous resolve()
        # calls for the same session_id don't both ask the factory.
        # Cleaned up after the agent lands in _cache.
        self._instantiation_locks: dict[str, asyncio.Lock] = {}
        # Inflight-use refcount per session. Eviction must not close
        # an agent whose dispatch task is still mid-turn — closing
        # the agent's owned session_store mid-write produced
        # "Cannot operate on a closed database" sqlite warnings
        # under concurrent stress. Callers wrap usage in
        # ``async with pool.use(session_id) as agent``; ``get`` is
        # kept for tests and back-compat but does not pin.
        self._inflight: dict[str, int] = {}

    async def get(self, session_id: str) -> Agent:
        """Return the agent for ``session_id``, instantiating if absent.

        On a cache hit, the entry moves to the most-recently-used
        position. On a miss, the factory is awaited *outside* the
        pool-wide lock — agents can take seconds to instantiate
        (history loading + system-prompt build) and we don't want to
        block other sessions during that.
        """
        return await self._get_internal(session_id, pin=False)

    async def _get_internal(
        self,
        session_id: str,
        *,
        pin: bool,
    ) -> Agent:
        """Get + (optionally) atomically pin under a single lock pass.

        The pin must be visible to ``_evict_if_full_unlocked`` before
        it runs, otherwise the newly-added entry is the only unpinned
        candidate and gets evicted immediately. ``pool.use`` calls
        this with ``pin=True``.
        """
        async with self._lock:
            if session_id in self._cache:
                self._cache.move_to_end(session_id)
                if pin:
                    self._inflight[session_id] = self._inflight.get(session_id, 0) + 1
                return self._cache[session_id]
            inst_lock = self._instantiation_locks.setdefault(session_id, asyncio.Lock())

        async with inst_lock:
            # Re-check under the inst lock: another caller may have
            # finished instantiation while we were waiting.
            async with self._lock:
                if session_id in self._cache:
                    self._cache.move_to_end(session_id)
                    if pin:
                        self._inflight[session_id] = self._inflight.get(session_id, 0) + 1
                    return self._cache[session_id]

            agent = await self._factory(session_id)

            async with self._lock:
                self._cache[session_id] = agent
                self._cache.move_to_end(session_id)
                self._instantiation_locks.pop(session_id, None)
                if pin:
                    self._inflight[session_id] = self._inflight.get(session_id, 0) + 1
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

    @contextlib.asynccontextmanager
    async def use(self, session_id: str):
        """Yield the agent for ``session_id`` and refcount-pin it so
        :meth:`_evict_if_full_unlocked` won't close it mid-dispatch.

        Usage::

            async with pool.use(sid) as agent:
                await agent.run_turn(text)

        The pin survives across pool growth: if the cache hits its
        size cap while this entry is in use, eviction walks past it
        and drops the next-oldest unpinned entry instead.
        """
        # Pin atomically inside the same lock that handles cache
        # insertion + eviction so a concurrent get() can't evict the
        # just-added entry before this caller marks it in-use.
        agent = await self._get_internal(session_id, pin=True)
        try:
            yield agent
        finally:
            async with self._lock:
                n = self._inflight.get(session_id, 0) - 1
                if n <= 0:
                    self._inflight.pop(session_id, None)
                else:
                    self._inflight[session_id] = n

    async def _evict_if_full_unlocked(self) -> None:
        """Evict the oldest unpinned entry while over capacity. Caller
        holds ``self._lock``; eviction itself takes that lock
        recursively through :meth:`evict`, which would deadlock, so
        close the agent directly here.

        Pinned entries (refcount > 0 in :attr:`_inflight`) are
        skipped — closing an in-flight agent breaks its owned
        SessionStore mid-write. The most-recently-added entry is
        also skipped: it's the one the caller is about to use, so
        evicting it immediately would defeat the call. If every
        other cache slot is pinned, the pool exceeds ``max_size``
        transiently rather than break either the in-flight turn or
        the call that just landed.
        """
        while len(self._cache) > self.max_size:
            target_id: str | None = None
            # OrderedDict iterates oldest-first; the very last entry
            # is the just-added one — skip it.
            keys = list(self._cache.keys())
            for sid in keys[:-1]:
                if self._inflight.get(sid, 0) == 0:
                    target_id = sid
                    break
            if target_id is None:
                # Everyone older is busy. Don't touch the newest
                # entry — the caller is about to use it.
                return
            agent = self._cache.pop(target_id)
            # Release the lock for the close — close may do I/O.
            self._lock.release()
            try:
                await self._close_agent(agent, target_id)
            finally:
                await self._lock.acquire()

    async def _close_agent(self, agent: Agent, session_id: str) -> None:
        try:
            close = getattr(agent, "close", None)
            if close is None:
                return
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("agent.close failed during eviction for %s", session_id)

    # ---- inspection ----

    @property
    def size(self) -> int:
        return len(self._cache)

    def contains(self, session_id: str) -> bool:
        return session_id in self._cache

    def session_ids(self) -> list[str]:
        """Return cached session ids in LRU order (oldest first)."""
        return list(self._cache.keys())
