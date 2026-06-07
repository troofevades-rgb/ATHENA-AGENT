"""``/steer`` and ``/queue`` — in-flight redirection of the agent.

``/steer <message>`` pushes ``message`` to the per-session queue. The agent
drains every pending steer before sending the next user prompt to the
model, prepending each as a synthetic ``[/steer] <message>`` user message.

``/steer clear`` empties the queue without consuming any steers.

``/queue`` lists pending steers without removing them.
"""

from __future__ import annotations

from typing import Any

from .. import ui
from ..steer.queue import GLOBAL_STEER_QUEUE
from . import command


@command("steer")
def cmd_steer(agent: Any, arg: str = "") -> str:
    arg = arg.strip()
    session_id = agent.session_id or "_no_session"

    if not arg:
        ui.error("usage: /steer <message>  |  /steer clear")
        return ""

    if arg == "clear":
        count = GLOBAL_STEER_QUEUE.clear(session_id)
        ui.info(f"cleared {count} pending steer(s)")
        return ""

    GLOBAL_STEER_QUEUE.push(session_id, arg)
    pending = len(GLOBAL_STEER_QUEUE.list(session_id))
    ui.info(f"steer queued ({pending} pending). Delivered before your next prompt.")
    return ""


@command("queue")
def cmd_queue(agent: Any, arg: str = "") -> str:
    session_id = agent.session_id or "_no_session"
    pending = GLOBAL_STEER_QUEUE.list(session_id)
    if not pending:
        ui.info("no pending steers")
        return ""
    ui.console.print(f"[bold]pending steers ({len(pending)}):[/]")
    for i, message in enumerate(pending, 1):
        ui.console.print(f"  {i}. {message}")
    return ""
