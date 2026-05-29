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


# Import command modules so they register.
#
# R3 (Phase 18.1): every slash-command module lives at a bare name --
# matches the cli/ convention and the already-consolidated single-file
# commands (computer, board, update). The directory itself signals
# "this is a command"; the _cmd / _cmds / _command suffixes were
# redundant noise.
from . import (
    board,  # noqa: F401 — T6-06 /board view + /board clear
    checkpoint,  # noqa: F401 — T3-03 /checkpoint, /rollback-to, /checkpoints
    clear,  # noqa: F401
    compact,  # noqa: F401
    computer,  # noqa: F401 — /computer status
    cost,  # noqa: F401
    cwd,  # noqa: F401
    dump,  # noqa: F401
    goal,  # noqa: F401
    help,  # noqa: F401
    hooks,  # noqa: F401
    init,  # noqa: F401
    loop,  # noqa: F401
    mcp,  # noqa: F401
    memory,  # noqa: F401
    model,  # noqa: F401
    models,  # noqa: F401
    plan,  # noqa: F401
    resume,  # noqa: F401
    review,  # noqa: F401
    save,  # noqa: F401
    skill,  # noqa: F401 — /skill import, /skill reload
    status,  # noqa: F401
    steer,  # noqa: F401
    theme,  # noqa: F401 — /theme inspect / switch / save
    tools,  # noqa: F401
    video,  # noqa: F401 — /video set <backend> + auth status
)
