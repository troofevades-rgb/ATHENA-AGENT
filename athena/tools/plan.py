"""ExitPlanMode tool. Used together with the agent's plan-mode flag.

Behavior:
- The agent enters plan mode either via `/plan` or by calling EnterPlanMode.
- While in plan mode, write/edit/bash tools are blocked. Only read-only
  tools work (Read, Glob, Grep, WebFetch, WebSearch).
- The agent calls ExitPlanMode with a proposed plan. The user is shown the
  plan and asked whether to proceed. If yes, the agent exits plan mode and
  begins executing.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import ui
from .registry import tool

# Module-level flag, read by agent.py at tool-dispatch time.
_PLAN_MODE = False

# Listeners notified on every plan-mode state change. The REPL
# registers a callback at startup so the TUI gets an immediate
# StatusUpdateEvent instead of waiting for the next natural
# status push (which can be a full turn away). Plain function
# list — no thread safety needed because plan-mode transitions
# only happen on the main thread.
_LISTENERS: list[Callable[[bool], None]] = []


def register_plan_mode_listener(fn: Callable[[bool], None]) -> None:
    """Subscribe to plan-mode transitions. ``fn`` receives the new
    state (True = in plan mode). Registration is idempotent."""
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def _notify(state: bool) -> None:
    for fn in _LISTENERS:
        try:
            fn(state)
        except Exception:  # noqa: BLE001 — listener crashing must not
            # break plan-mode transitions. Surfaced via the standard
            # logging path.
            import logging
            logging.getLogger(__name__).exception(
                "plan-mode listener raised; continuing",
            )


def is_plan_mode() -> bool:
    return _PLAN_MODE


def enter_plan_mode() -> None:
    global _PLAN_MODE
    if _PLAN_MODE:
        return
    _PLAN_MODE = True
    _notify(True)


def exit_plan_mode_silent() -> None:
    global _PLAN_MODE
    if not _PLAN_MODE:
        return
    _PLAN_MODE = False
    _notify(False)


# Tools that are still allowed in plan mode (read-only).
PLAN_MODE_ALLOWED = {
    "Read",
    "read_file",
    "Glob",
    "glob",
    "Grep",
    "grep",
    "WebFetch",
    "web_fetch",
    "WebSearch",
    "web_search",
    "list_dir",
    "TaskCreate",
    "TaskUpdate",
    "TaskList",
    "AskUserQuestion",
    "ExitPlanMode",
    "EnterPlanMode",
    "write_memory",
    "delete_memory",
    "list_memories",
}


@tool(
    name="ExitPlanMode",
    toolset="core",
    description=(
        "Use this tool when you are in plan mode and have finished drafting "
        "a plan. Pass the plan text. The user will be shown the plan and "
        "asked to approve it. If they approve, plan mode exits and you can "
        "begin implementing. If they don't, stay in plan mode and revise."
    ),
    parameters={
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": "Markdown-formatted plan to present to the user.",
            },
        },
        "required": ["plan"],
    },
)
def ExitPlanMode(plan: str) -> str:
    global _PLAN_MODE
    if not _PLAN_MODE:
        return "ERROR: not in plan mode"
    ui.console.print()
    ui.console.print("[bold cyan]── Proposed plan ──[/]")
    ui.console.print(plan)
    ui.console.print("[bold cyan]───────────────────[/]")
    if ui.confirm("Approve and start executing?", default=False):
        _PLAN_MODE = False
        _notify(False)
        return "Plan approved by user. You may now begin implementing it."
    return "Plan NOT approved. Stay in plan mode and revise."


@tool(
    name="EnterPlanMode",
    toolset="core",
    description=(
        "Enter plan mode. While in plan mode, write/edit/bash tools are "
        "blocked; only read-only investigation tools work. Use this when "
        "the user asks for a plan, design, or proposal before any changes."
    ),
    parameters={"type": "object", "properties": {}},
)
def EnterPlanMode() -> str:
    global _PLAN_MODE
    if not _PLAN_MODE:
        _PLAN_MODE = True
        _notify(True)
    return (
        "Entered plan mode. Write/edit/bash tools are blocked; use Read, "
        "Glob, Grep, WebFetch, and WebSearch to investigate. When ready, "
        "call ExitPlanMode with the plan text."
    )
