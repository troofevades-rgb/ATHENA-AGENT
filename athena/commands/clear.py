"""``/clear`` — reset conversation history (keeps the system prompt)."""

from __future__ import annotations

from typing import Any

from . import command


@command("clear")
def cmd_clear(agent: Any, arg: str = "") -> str:
    agent.reset()
    return ""
