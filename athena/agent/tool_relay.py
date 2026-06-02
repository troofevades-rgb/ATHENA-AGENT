"""Per-context sink for relaying selected tool RESULTS to a gateway chat.

The gateway normally sends a chat user only the model's final text (plus
progress lines and media files). A tool whose *output is the answer* —
``skills_list``, a status dump — renders its result to the daemon's
terminal but never reaches Discord/Telegram, so the chat user sees only
the model's paraphrase.

Tools opt in by declaring ``gateway_relay=True`` (see
:class:`athena.tools.registry.Tool`); the agent loop calls
:func:`emit_tool_result` after such a tool runs, and the gateway adapter
binds a sink that delivers the result to the chat (truncated/chunked).

No-op when no sink is bound (the terminal and forks bind nothing). Same
ContextVar mechanics as :mod:`athena.agent.progress` and
:mod:`athena.agent.media_artifacts`, so ``asyncio.to_thread`` copies the
sink into the worker thread that runs the agent loop. The sink must not
block or raise; :func:`emit_tool_result` swallows any exception.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

ToolResultSinkFn = Callable[[str, str], None]
"""(tool_name, result_text) -> None. Fire-and-forget; must not block or raise."""


_tool_result: contextvars.ContextVar[ToolResultSinkFn | None] = contextvars.ContextVar(
    "athena_tool_result_sink", default=None
)


def set_tool_result_sink(
    fn: ToolResultSinkFn | None,
) -> contextvars.Token[ToolResultSinkFn | None]:
    """Bind the active tool-result sink. Returns a token for :func:`reset_tool_result_sink`."""
    return _tool_result.set(fn)


def reset_tool_result_sink(token: contextvars.Token[ToolResultSinkFn | None]) -> None:
    _tool_result.reset(token)


def emit_tool_result(tool_name: str, result_text: str) -> None:
    """Report a relay-eligible tool's result to the bound sink, if any.

    No-op when unbound. Best-effort: any exception in the sink is logged
    at debug and swallowed so relaying can never break a turn.
    """
    sink = _tool_result.get()
    if sink is None:
        return
    try:
        sink(tool_name, result_text)
    except Exception:  # noqa: BLE001 — relay is best-effort
        logger.debug("tool-result sink raised; ignoring", exc_info=True)
