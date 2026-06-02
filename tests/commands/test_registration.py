"""Every command module under ``athena/commands/`` MUST be imported
in ``athena/commands/__init__.py`` so its ``@command`` decorator
fires. The unit suite for an individual command file can pass while
the slash form is dead (the test imports the function directly,
bypassing the registry) — this test closes that gap.
"""

from __future__ import annotations

from pathlib import Path

import athena.commands as commands_pkg  # noqa: F401 — populates _COMMANDS

# Commands that have a slash form AND are expected to be reachable
# via ``/<name>`` at the REPL. The dict maps the expected slash
# name to the module it lives in — kept explicit so a future
# rename trips this test on the rename, not the next runbook
# pass.
EXPECTED_SLASH_COMMANDS: dict[str, str] = {
    "board": "athena/commands/board.py",
    "checkpoint": "athena/commands/checkpoint.py",
    "checkpoints": "athena/commands/checkpoint.py",
    "clear": "athena/commands/clear.py",
    "compact": "athena/commands/compact.py",
    "computer": "athena/commands/computer.py",
    "cost": "athena/commands/cost.py",
    "cwd": "athena/commands/cwd.py",
    "dump": "athena/commands/dump.py",
    "goal": "athena/commands/goal.py",
    "godmode": "athena/commands/godmode.py",
    "help": "athena/commands/help.py",
    "hooks": "athena/commands/hooks.py",
    "init": "athena/commands/init.py",
    "loop": "athena/commands/loop.py",
    "mcp": "athena/commands/mcp.py",
    "memory": "athena/commands/memory.py",
    "model": "athena/commands/model.py",
    "models": "athena/commands/models.py",
    "plan": "athena/commands/plan.py",
    "queue": "athena/commands/steer.py",
    "resume": "athena/commands/resume.py",
    "review": "athena/commands/review.py",
    "save": "athena/commands/save.py",
    "skill": "athena/commands/skill.py",
    "status": "athena/commands/status.py",
    "steer": "athena/commands/steer.py",
    "subgoal": "athena/commands/goal.py",
    "theme": "athena/commands/theme.py",
    "tools": "athena/commands/tools.py",
    "video": "athena/commands/video.py",
}


def test_every_expected_command_is_registered():
    """Each name above must resolve via the slash dispatcher.

    Catches the class of regression we hit at runbook §1.8 — a
    command file with passing unit tests but missing from
    ``commands/__init__.py``'s side-effect import list.
    """
    from athena.commands import get_command

    missing = sorted(name for name in EXPECTED_SLASH_COMMANDS if get_command(name) is None)
    assert not missing, (
        "These slash commands are unreachable via the dispatcher — "
        "their modules need an entry in athena/commands/__init__.py: "
        f"{missing}"
    )


def test_help_text_mentions_every_registered_slash_command():
    """``/help`` shows the slash commands a user can type. If a new
    command is registered but not added to the help text, users
    can't discover it — and we caught this with /board and /video
    during runbook §1.8."""
    from athena.commands.help import SLASH_HELP

    missing = [name for name in EXPECTED_SLASH_COMMANDS if f"/{name}" not in SLASH_HELP]
    assert not missing, (
        f"These slash commands are registered but not mentioned in "
        f"SLASH_HELP: {missing}. Add a one-line description to "
        f"athena/commands/help.py:SLASH_HELP."
    )


def test_help_does_not_advertise_unregistered_commands():
    """Inverse check: if SLASH_HELP names a command that isn't in
    the dispatcher, the doc lies. Catches drift the other way."""
    import re

    from athena.commands import get_command

    # Extract every ``/word`` token from the help text and verify
    # each resolves. Only ``/exit /quit /q`` are dispatched inline
    # in ``__main__.py:_handle_slash`` -- they signal "break the
    # outer REPL loop" by returning False, which the @command
    # return contract can't express. Everything else, including
    # ``plan-exit`` and ``loop-stop``, is registered via the
    # decorator (verified by _ACTUAL_INLINE_REPL_COMMANDS pin
    # below).
    inline_only = _ACTUAL_INLINE_REPL_COMMANDS
    seen = set(
        re.findall(
            r"^/([\w-]+)",
            __import__(
                "athena.commands.help",
                fromlist=["SLASH_HELP"],
            ).SLASH_HELP,
            re.MULTILINE,
        )
    )
    advertised = seen - inline_only
    missing = sorted(name for name in advertised if get_command(name) is None)
    assert not missing, (
        f"SLASH_HELP advertises commands that aren't registered: "
        f"{missing}. Either register them or remove from help."
    )


# The single inline-dispatch exception in ``__main__.py:_handle_slash``.
# Every other slash command goes through ``commands.get_command(name)``.
# Pinned so a future "let me just inline one more for convenience"
# refactor breaks the test instead of silently fragmenting the
# dispatch architecture.
_ACTUAL_INLINE_REPL_COMMANDS: frozenset[str] = frozenset({"exit", "quit", "q"})


def test_repl_dispatcher_has_only_documented_inline_exception():
    """The slash-dispatch architecture is single-path: every command
    goes through ``commands.get_command()`` EXCEPT ``/exit /quit /q``,
    which inline-return False to break the REPL loop.

    Without this pin, a future shortcut ("let me just add this one
    inline for performance") would silently fragment the dispatch
    surface. ATHENA.md documents the single-exception design;
    this test enforces it.

    Implementation: parse ``_handle_slash`` source, extract the
    ``cmd in (...)`` literal that gates the inline branch, and
    assert it matches the documented set.
    """
    import ast
    import inspect

    import athena.__main__ as main_mod

    src = inspect.getsource(main_mod._handle_slash)
    tree = ast.parse(src)

    # Find every ``Compare`` node testing ``cmd <op> ...`` for
    # equality / membership. The inline branch is the only ``cmd in
    # (...)`` / ``cmd == ...`` check in the function before the
    # registry lookup.
    inline_commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "cmd"):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.In)):
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    inline_commands.add(comparator.value)
                elif isinstance(comparator, ast.Tuple):
                    for elt in comparator.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            inline_commands.add(elt.value)

    assert inline_commands == set(_ACTUAL_INLINE_REPL_COMMANDS), (
        f"_handle_slash inline-dispatches {inline_commands}, but the "
        f"documented single-exception set is "
        f"{set(_ACTUAL_INLINE_REPL_COMMANDS)}. Either route the new "
        "command through the @command registry or update "
        "_ACTUAL_INLINE_REPL_COMMANDS + ATHENA.md to reflect the new "
        "architecture."
    )


def test_plan_exit_and_loop_stop_are_registered_not_inline():
    """Regression pin for a stale-docs trap: the older test treated
    ``plan-exit`` and ``loop-stop`` as inline, but both are
    registered via ``@command``. Without this pin the registration
    check could silently skip them."""
    from athena.commands import get_command

    assert get_command("plan-exit") is not None
    assert get_command("loop-stop") is not None
