"""``/goal`` — set / show / clear the persistent invariant.

The goal is written to ``<profile_dir>/goal.txt`` and re-injected into the
system prompt on every rebuild. After mutating, the command asks the agent
to rebuild its system message in place so the change takes effect without
``/clear``-ing history.
"""
from __future__ import annotations

from . import command
from .. import ui
from ..goal.invariant import clear_goal, get_goal, set_goal


@command("goal")
def cmd_goal(agent, arg: str = "") -> str:
    arg = arg.strip()
    profile_dir = agent._profile_dir()

    if not arg or arg == "show":
        current = get_goal(profile_dir)
        if current:
            ui.console.print(f"[bold]current goal:[/] {current}")
        else:
            ui.info("no goal set")
        return ""

    if arg == "clear":
        had_goal = clear_goal(profile_dir)
        agent.reload_goal()
        ui.info("goal cleared" if had_goal else "no goal was set")
        return ""

    try:
        set_goal(profile_dir, arg)
    except ValueError as e:
        ui.error(str(e))
        return ""
    agent.reload_goal()
    ui.info(f"goal set: {arg}")
    return ""
