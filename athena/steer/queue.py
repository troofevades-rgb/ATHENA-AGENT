"""Pending steer queue — thread-safe, per-session, in-memory.

A *steer* is a brief redirect the user supplies in-flight without canceling
the current turn. Steers are queued and delivered to the agent *before*
the next user prompt. Multiple steers accumulate and replay in FIFO order.

The queue is in-memory only. Gateway adapters (Phase 10) running on
separate threads call ``GLOBAL_STEER_QUEUE.push(session_id, message)`` and
the agent's run loop calls ``GLOBAL_STEER_QUEUE.drain(session_id)`` before
sending the next user message to the model.
"""

from __future__ import annotations

import threading
from collections import deque


class SteerQueue:
    """Per-session FIFO queue of steer messages. All operations are
    serialized by a single lock; contention is negligible because pushes
    and drains are short-lived."""

    def __init__(self) -> None:
        self._q: dict[str, deque[str]] = {}
        self._lock = threading.Lock()

    def push(self, session_id: str, message: str) -> None:
        """Add ``message`` to the back of ``session_id``'s queue."""
        with self._lock:
            self._q.setdefault(session_id, deque()).append(message)

    def pop(self, session_id: str) -> str | None:
        """Remove and return the oldest steer for ``session_id`` (or ``None``)."""
        with self._lock:
            q = self._q.get(session_id)
            if not q:
                return None
            return q.popleft()

    def drain(self, session_id: str) -> list[str]:
        """Pop every steer for ``session_id`` in FIFO order. Empties the queue."""
        with self._lock:
            q = self._q.pop(session_id, None)
            return list(q) if q else []

    def list(self, session_id: str) -> list[str]:
        """Return a snapshot of pending steers without removing them."""
        with self._lock:
            return list(self._q.get(session_id, ()))

    def clear(self, session_id: str) -> int:
        """Drop every steer for ``session_id``. Returns how many were removed."""
        with self._lock:
            q = self._q.pop(session_id, None)
            return len(q) if q else 0


# Module-level singleton. Gateway adapters and slash commands both use this.
GLOBAL_STEER_QUEUE = SteerQueue()
