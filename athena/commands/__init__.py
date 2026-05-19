"""Slash command handlers.

Each command is a function that takes (agent, arg) and either:
  - returns None / continues normally
  - returns a string to inject as the next user message
  - returns False to exit the REPL

Commands are registered by name; '/foo arg' looks up 'foo' here.

Renamed from ``athena/skills/`` in Phase 1 to free the name for the new
file-based skill format introduced later in this phase.
"""

from __future__ import annotations

from collections.abc import Callable

# (agent, arg) -> str | None | bool
CommandFn = Callable[..., object]

_COMMANDS: dict[str, CommandFn] = {}


def command(name: str):
    def deco(fn: CommandFn) -> CommandFn:
        _COMMANDS[name] = fn
        return fn

    return deco


def get_command(name: str) -> CommandFn | None:
    return _COMMANDS.get(name)


def all_commands() -> dict[str, CommandFn]:
    return dict(_COMMANDS)


# Import command modules so they register
from . import (
    compact,  # noqa: F401
    goal,  # noqa: F401
    init,  # noqa: F401
    loop,  # noqa: F401
    memory_command,  # noqa: F401
    plan_command,  # noqa: F401
    resume,  # noqa: F401
    review,  # noqa: F401
    steer,  # noqa: F401
)
