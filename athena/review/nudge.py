"""Per-session counter that fires the review fork on a fixed cadence.

State is a module-level dict keyed by session_id. Resetting clears the
session's entry — useful when an agent closes or the test suite needs a
clean slate.
"""

from __future__ import annotations

import threading

_counters: dict[str, int] = {}
_lock = threading.Lock()


def increment_and_check(session_id: str | None, interval: int) -> bool:
    """Increment the per-session counter and return True when the new value
    is a positive multiple of ``interval``.

    A None ``session_id`` (the agent is running without session persistence)
    is treated as a no-op and never fires.
    """
    if session_id is None or interval <= 0:
        return False
    with _lock:
        n = _counters.get(session_id, 0) + 1
        _counters[session_id] = n
    return n > 0 and n % interval == 0


def value(session_id: str) -> int:
    """Current count for ``session_id`` (zero if absent)."""
    return _counters.get(session_id, 0)


def reset(session_id: str | None) -> None:
    if session_id is None:
        return
    with _lock:
        _counters.pop(session_id, None)


def reset_all() -> None:
    """Drop every counter — used by tests so they don't see each other's state."""
    with _lock:
        _counters.clear()
