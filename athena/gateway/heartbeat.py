"""Per-session liveness tracker.

Tool calls bump :meth:`HeartbeatTracker.mark` so the adapter can keep a
typing indicator alive and so the stale-lock healer can tell which
sessions still have a running worker.

Uses :func:`time.monotonic` — never wall-clock — because the only thing
this tracker is asked about is *elapsed time since the last mark* and
clock skew during NTP sync would otherwise produce spurious staleness.
"""

from __future__ import annotations

import time


class HeartbeatTracker:
    def __init__(self) -> None:
        self._marks: dict[str, float] = {}

    def mark(self, session_id: str) -> None:
        """Record that ``session_id`` is alive *now*."""
        self._marks[session_id] = time.monotonic()

    def age(self, session_id: str) -> float | None:
        """Seconds since the last :meth:`mark` for ``session_id``, or
        ``None`` if the session was never marked."""
        m = self._marks.get(session_id)
        return None if m is None else time.monotonic() - m

    def clear(self, session_id: str) -> None:
        """Forget the session — typically called when an agent is
        evicted from the pool."""
        self._marks.pop(session_id, None)
