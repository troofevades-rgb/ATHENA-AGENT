"""ACP slash command handlers.

The IDE forwards ``/`` commands from the chat input via
``session/slash_command``. Each command produces a synchronous text
response shown in the chat:

- ``/steer <message>`` — push a steer onto the session's queue
  (drains before the next user prompt).
- ``/queue`` — list pending steers.
- ``/queue clear`` — drop them.
- ``/goal`` (no arg) — show the current persistent goal.
- ``/goal <text>`` — set the goal (re-injected into the system
  prompt on every rebuild).
- ``/goal clear`` — drop the goal.

Unknown commands return a friendly "unknown command" message rather
than erroring; the IDE shows it in the chat.

Slash commands run on the asyncio loop; the underlying steer queue
is thread-safe (``threading.Lock``) and goal I/O is straightforward
file work, so neither requires special bridging.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..goal.invariant import clear_goal, get_goal, set_goal
from ..steer.queue import GLOBAL_STEER_QUEUE

if TYPE_CHECKING:
    from ..agent.core import Agent

logger = logging.getLogger(__name__)


_KNOWN = frozenset({"steer", "queue", "goal"})


async def handle_slash(
    params: dict[str, Any],
    sessions: dict[str, "Agent"],
) -> dict[str, Any]:
    """Route a slash command to its handler.

    ``params`` shape (from the IDE): ``{"session_id": ..., "command":
    "steer", "argument": "focus on tests"}``. Both ``command`` (without
    leading slash) and an optional ``argument`` are accepted.
    """
    sid = str(params.get("session_id") or "")
    cmd = str(params.get("command") or "").lstrip("/").lower()
    arg = str(params.get("argument") or "").strip()

    if not sid:
        return _err("missing session_id")
    if cmd not in _KNOWN:
        return _err(f"unknown slash command: /{cmd}")

    agent = sessions.get(sid)
    profile_dir = _profile_dir_for(agent, sid)

    if cmd == "steer":
        if not arg:
            return _result("usage: /steer <message>")
        GLOBAL_STEER_QUEUE.push(sid, arg)
        return _result(f"steer queued: {arg}")

    if cmd == "queue":
        if arg == "clear":
            removed = GLOBAL_STEER_QUEUE.clear(sid)
            return _result(f"cleared {removed} pending steer(s)")
        pending = GLOBAL_STEER_QUEUE.list(sid)
        if not pending:
            return _result("(no pending steers)")
        return _result("\n".join(f"- {m}" for m in pending))

    if cmd == "goal":
        if not arg:
            current = get_goal(profile_dir) if profile_dir else None
            return _result(current or "(no goal set)")
        if arg == "clear":
            removed = clear_goal(profile_dir) if profile_dir else False
            if removed and agent is not None:
                agent.goal = None
                _rebuild_system_prompt(agent)
            return _result("goal cleared")
        if profile_dir is not None:
            set_goal(profile_dir, arg)
        if agent is not None:
            agent.goal = arg
            _rebuild_system_prompt(agent)
        return _result(f"goal set: {arg}")

    # Should be unreachable given the _KNOWN gate above.
    return _err(f"unhandled slash command: /{cmd}")  # pragma: no cover


def _profile_dir_for(agent: "Agent | None", session_id: str) -> Path | None:
    """Best-effort profile dir resolution.

    The agent (if present) carries its own profile dir via cfg. With
    no agent in the sessions dict we fall back to None — goal commands
    in that case operate on no profile and return a clear message.
    """
    if agent is None:
        return None
    try:
        return agent._profile_dir()
    except Exception:
        return None


def _rebuild_system_prompt(agent: "Agent") -> None:
    """Re-render the agent's system prompt so the new goal lands in
    the next request to the model. The Agent's :meth:`reload_goal`
    is the same hook the REPL /goal slash command uses."""
    reload_goal = getattr(agent, "reload_goal", None)
    if reload_goal is not None:
        try:
            reload_goal()
        except Exception:
            logger.warning(
                "Agent.reload_goal failed for ACP /goal", exc_info=True,
            )


def _result(text: str) -> dict[str, str]:
    return {"result": text}


def _err(text: str) -> dict[str, str]:
    return {"result": f"error: {text}"}
