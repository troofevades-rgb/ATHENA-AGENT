"""Cancel hooks for unblocking the main thread mid-stream.

The problem: ``_thread.interrupt_main()`` only fires
``KeyboardInterrupt`` at Python bytecode boundaries. When the main
thread is blocked in C code — typically ``socket.recv`` inside
``httpx.Client.stream`` waiting for the next LLM SSE chunk — the
signal queues but doesn't deliver until the C call returns. With
a slow local model and a long generation, that can be many minutes.
The user pressing ESC sees nothing happen and has no recourse
short of killing the terminal.

The fix: register thread-safe "cancel" callbacks here. When the
gateway receives an InterruptCommand, it calls
:func:`fire_cancel_hooks` IN ADDITION to ``_thread.interrupt_main()``.
A cancel hook typically closes the provider's httpx client — the
socket gets shut down, the blocked recv returns with an error,
the agent's exception handler runs, and the queued KeyboardInterrupt
finally delivers.

Hooks must be FAST and NEVER raise. They run on the gateway
reader thread; a raise would kill that thread and stop further
interrupts. The dispatcher catches everything defensively.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_hooks: list[Callable[[], None]] = []


def register_cancel_hook(fn: Callable[[], None]) -> None:
    """Register ``fn`` to fire when an interrupt arrives. Idempotent —
    registering the same callable twice only stores it once."""
    with _lock:
        if fn not in _hooks:
            _hooks.append(fn)


def unregister_cancel_hook(fn: Callable[[], None]) -> None:
    """Remove ``fn`` from the hook list. Safe to call with a
    function that was never registered (no-op)."""
    with _lock:
        try:
            _hooks.remove(fn)
        except ValueError:
            pass


def fire_cancel_hooks() -> None:
    """Run every registered cancel hook. Catches every exception
    individually so a buggy hook can't block the others. Called
    from the gateway reader thread after _thread.interrupt_main(),
    so the order is:

      1. Set the SIGINT-equivalent flag on main (queued, deferred
         to the next bytecode boundary)
      2. Close in-flight sockets so the bytecode boundary actually
         gets reached (recv returns with an error)
      3. KeyboardInterrupt delivers, agent unwinds
    """
    with _lock:
        snapshot = list(_hooks)
    for fn in snapshot:
        try:
            fn()
        except Exception:  # noqa: BLE001
            logger.exception("cancel hook %r raised; continuing", fn)


def _reset_for_tests() -> None:
    """Test-only — drop all registered hooks so test isolation
    isn't dependent on cleanup ordering."""
    with _lock:
        _hooks.clear()
