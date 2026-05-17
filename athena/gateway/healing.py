"""Stale-session-lock detection and force-release.

A per-session :class:`asyncio.Lock` ensures one in-flight turn per
session, but if the task holding it dies without releasing (process
crash mid-tool-call, killed coroutine, ``CancelledError`` swallowed in
the wrong place) the session wedges. This module heals that.

Heuristic: a lock is *stale* when it is held AND the session's
heartbeat is older than :data:`STALE_THRESHOLD_SECONDS`. The healer
then cracks :class:`asyncio.Lock`'s internals to force-release it.

The private-attribute access is deliberate — it's the same fix Hermes
Agent shipped for issue #11016 — and is wrapped in a broad ``try`` so
that an upstream rename in CPython degrades to "lock stays locked" not
"healer crashes the daemon".
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .heartbeat import HeartbeatTracker

logger = logging.getLogger(__name__)

STALE_THRESHOLD_SECONDS = 60.0


class StaleSessionLockHealer:
    def is_stale(
        self, session_id: str, heartbeat: "HeartbeatTracker"
    ) -> bool:
        """True if the session has a tracked heartbeat older than the
        threshold. A session with no heartbeat is *not* stale — it has
        simply never run, so its lock (if held) is fresh."""
        age = heartbeat.age(session_id)
        return age is not None and age > STALE_THRESHOLD_SECONDS

    def force_release(self, lock: asyncio.Lock) -> bool:
        """Forcibly unlock ``lock`` and wake one waiter.

        Returns True on success, False if asyncio's internals have
        shifted under us. Either way the daemon stays up.
        """
        try:
            lock._locked = False  # type: ignore[attr-defined]
            waiters = getattr(lock, "_waiters", None) or []
            for w in list(waiters):
                if not w.done():
                    w.set_result(True)
                    break
            return True
        except Exception:
            logger.exception(
                "force_release failed; lock remains locked. "
                "asyncio internals may have changed."
            )
            return False
