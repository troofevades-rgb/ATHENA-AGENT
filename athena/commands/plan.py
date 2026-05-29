"""/plan — toggle plan mode, or enter plan mode and seed a prompt."""

from __future__ import annotations

from .. import ui
from ..tools import plan as plan_mod
from . import command


@command("plan")
def cmd_plan(agent, arg: str = "") -> str:
    arg = arg.strip()
    plan_mod.enter_plan_mode()
    if not arg:
        ui.info("entered plan mode. write/edit/bash blocked. /plan-exit to leave.")
        return ""
    ui.info(f"entered plan mode for: {arg!r}")
    return f"Draft a plan for: {arg}\n\nUse Read/Glob/Grep to investigate. Call ExitPlanMode with the plan when ready."


@command("plan-exit")
def cmd_plan_exit(agent, arg: str = "") -> str:
    plan_mod.exit_plan_mode_silent()
    ui.info("plan mode exited (without execution)")
    return ""
