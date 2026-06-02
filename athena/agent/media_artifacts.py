"""Per-context sink for media artifacts a turn produced (video/image files).

A terminal user finds a generated file by the path the tool prints. A
gateway user can't reach the server's filesystem, so the file itself has
to be delivered into the chat. Tools that produce a deliverable local
file call :func:`emit_media_artifact` with its path; the gateway adapter
binds a sink that collects the paths and ``send_file``s each one after
the turn.

No-op when no sink is bound (the terminal and forks bind nothing). The
sink is a ``Callable[[str], None]`` on a ContextVar, so — exactly like
:mod:`athena.agent.progress` and the approval callback —
``asyncio.to_thread`` copies it into the worker thread that runs the
agent loop. The sink must not block or raise; :func:`emit_media_artifact`
swallows any exception so artifact reporting can never break a turn.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

MediaSinkFn = Callable[[str], None]
"""(absolute_file_path) -> None. Fire-and-forget; must not block or raise."""


_media: contextvars.ContextVar[MediaSinkFn | None] = contextvars.ContextVar(
    "athena_media_sink", default=None
)


def set_media_sink(fn: MediaSinkFn | None) -> contextvars.Token[MediaSinkFn | None]:
    """Bind the active media-artifact sink. Returns a token for :func:`reset_media_sink`."""
    return _media.set(fn)


def reset_media_sink(token: contextvars.Token[MediaSinkFn | None]) -> None:
    _media.reset(token)


def emit_media_artifact(path: str) -> None:
    """Report a deliverable local media file to the bound sink, if any.

    No-op when unbound. Best-effort: any exception in the sink is logged
    at debug and swallowed.
    """
    sink = _media.get()
    if sink is None:
        return
    try:
        sink(path)
    except Exception:  # noqa: BLE001 — artifact delivery is best-effort
        logger.debug("media sink raised; ignoring", exc_info=True)
