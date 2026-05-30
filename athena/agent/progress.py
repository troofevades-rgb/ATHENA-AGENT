"""Per-context progress sink for surfacing in-turn activity.

The terminal UI renders tool rounds live, but a turn driven over the
gateway runs ``run_until_done`` synchronously on a worker thread and
only the *final* assistant message is sent to the chat. For a long
multi-tool turn that leaves the user staring at a typing indicator
with no idea whether the agent is working or wedged.

This module is the seam: the agent loop calls :func:`emit_progress`
at each tool-call round; whatever sink is bound on the current context
receives a short human-readable line. The terminal binds nothing (it
already streams), forks bind nothing (silent), and the gateway adapter
binds a sink that ships the line to the chat.

The sink is a plain ``Callable[[str], None]`` bound via a ContextVar,
so — exactly like the approval callback — ``asyncio.to_thread`` copies
it into the worker thread that runs the agent loop. The sink must be
non-blocking and must never raise; :func:`emit_progress` swallows any
exception so progress reporting can never break a turn.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]
"""(message) -> None. Fire-and-forget; must not block or raise."""


_progress: contextvars.ContextVar[ProgressFn | None] = contextvars.ContextVar(
    "athena_progress_sink", default=None
)


def set_progress_sink(fn: ProgressFn | None) -> contextvars.Token[ProgressFn | None]:
    """Bind the active progress sink. Returns a token for :func:`reset_progress_sink`."""
    return _progress.set(fn)


def reset_progress_sink(token: contextvars.Token[ProgressFn | None]) -> None:
    _progress.reset(token)


def emit_progress(message: str) -> None:
    """Send ``message`` to the bound sink, if any. No-op when unbound.

    Best-effort: any exception in the sink is logged at debug and
    swallowed so progress reporting can never break the turn.
    """
    sink = _progress.get()
    if sink is None:
        return
    try:
        sink(message)
    except Exception:  # noqa: BLE001 — progress is best-effort
        logger.debug("progress sink raised; ignoring", exc_info=True)
