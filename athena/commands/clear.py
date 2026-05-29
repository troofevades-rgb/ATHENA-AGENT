"""``/clear`` — reset conversation history (keeps the system prompt)."""

from __future__ import annotations

from . import command


@command("clear")
def cmd_clear(agent, arg: str = "") -> str:
    agent.reset()
    return ""
