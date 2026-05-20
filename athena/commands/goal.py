"""``/goal`` + ``/subgoal`` — set / drive / inspect the goal (T5-07.4).

Two interactive commands sharing the goal state in
``<profile_dir>/goal.txt`` + ``<profile_dir>/goal_state.json``.

``/goal`` subcommands:

  /goal <text>      set/replace the goal (status=active, turns_taken=0)
  /goal             show text + status + turns + subgoals (alias: status)
  /goal status      same as bare /goal
  /goal pause       stop the continuation loop (status=paused)
  /goal resume      restart the loop; if exhausted, grant another
                    cfg.goal_max_turns on top of turns_taken
  /goal clear       remove goal.txt + goal_state.json

``/subgoal`` subcommands:

  /subgoal <text>   append a subgoal (advisory only)
  /subgoal done     mark the first not-done subgoal complete

After any mutation the agent's in-memory system prompt is
rebuilt via ``agent.reload_goal()`` so the change takes effect
without requiring ``/clear``.
"""

from __future__ import annotations

from .. import ui
from ..goal.invariant import clear_goal, get_goal, set_goal
from ..goal.state import (
    GoalState,
    Subgoal,
    clear_state,
    load_state,
    save_state,
)
from . import command


def _profile_dir(agent):
    return agent._profile_dir()


def _show(agent) -> None:
    pdir = _profile_dir(agent)
    text = get_goal(pdir)
    if not text:
        ui.info("no goal set")
        return
    state = load_state(pdir)
    ui.console.print(f"[bold]current goal:[/] {text}")
    if state is None:
        ui.info("(no state file yet — /goal will initialise it on first turn)")
        return
    ui.console.print(
        f"  status: [bold]{state.status}[/]  "
        f"turns: {state.turns_taken}/{state.max_turns}"
    )
    if state.subgoals:
        ui.console.print("  subgoals:")
        for sg in state.subgoals:
            marker = "✓" if sg.done else "•"
            ui.console.print(f"    {marker} {sg.text}")


def _max_turns(agent) -> int:
    """Read the configured turn cap, tolerating agents that
    don't expose a ``cfg`` (pre-T5-07 tests / minimal stubs)."""
    cfg = getattr(agent, "cfg", None)
    if cfg is None:
        return 25
    return int(getattr(cfg, "goal_max_turns", 25))


def _set_goal_and_state(agent, text: str) -> None:
    """Persist a fresh goal + reset its state to active. The
    state's max_turns comes from cfg; turns_taken starts at 0."""
    pdir = _profile_dir(agent)
    set_goal(pdir, text)
    max_turns = _max_turns(agent)
    state = GoalState(text=text, status="active", turns_taken=0, max_turns=max_turns)
    save_state(pdir, state)
    agent.reload_goal()
    ui.info(f"goal set: {text}  (status=active, max_turns={max_turns})")


def _pause(agent) -> None:
    pdir = _profile_dir(agent)
    state = load_state(pdir)
    if state is None:
        ui.info("no goal state to pause")
        return
    if state.status == "paused":
        ui.info("goal already paused")
        return
    state.status = "paused"
    save_state(pdir, state)
    agent.reload_goal()
    ui.info("goal paused — /goal resume to continue")


def _resume(agent) -> None:
    pdir = _profile_dir(agent)
    state = load_state(pdir)
    if state is None:
        ui.info("no goal state to resume")
        return
    was_exhausted = state.status == "exhausted"
    state.status = "active"
    if was_exhausted:
        # /resume after exhaustion grants another cfg.goal_max_turns
        # ON TOP OF turns_taken — status shows "turn 30/50" so the
        # total work stays visible. Doesn't reset to 0; that would
        # hide runaway.
        bump = _max_turns(agent)
        state.max_turns += bump
        ui.info(
            f"goal resumed — cap bumped by {bump} (now {state.turns_taken}/{state.max_turns})"
        )
    else:
        ui.info(f"goal resumed (status=active, {state.turns_taken}/{state.max_turns})")
    save_state(pdir, state)
    agent.reload_goal()


def _clear(agent) -> None:
    pdir = _profile_dir(agent)
    had_text = clear_goal(pdir)
    had_state = clear_state(pdir)
    agent.reload_goal()
    if had_text or had_state:
        ui.info("goal cleared")
    else:
        ui.info("no goal was set")


@command("goal")
def cmd_goal(agent, arg: str = "") -> str:
    arg = arg.strip()
    if not arg or arg == "show" or arg == "status":
        _show(agent)
        return ""
    if arg == "pause":
        _pause(agent)
        return ""
    if arg == "resume":
        _resume(agent)
        return ""
    if arg == "clear":
        _clear(agent)
        return ""

    # Anything else is taken as the new goal text. Set + reset
    # state.
    try:
        _set_goal_and_state(agent, arg)
    except ValueError as e:
        ui.error(str(e))
    return ""


@command("subgoal")
def cmd_subgoal(agent, arg: str = "") -> str:
    arg = arg.strip()
    pdir = _profile_dir(agent)
    state = load_state(pdir)
    if state is None:
        ui.error("no goal set — use /goal <text> first, then /subgoal")
        return ""

    if not arg:
        # Bare /subgoal prints the list. Symmetric with /goal.
        if not state.subgoals:
            ui.info("no subgoals")
            return ""
        for sg in state.subgoals:
            marker = "✓" if sg.done else "•"
            ui.console.print(f"  {marker} {sg.text}")
        return ""

    if arg == "done":
        pending = state.first_pending_subgoal()
        if pending is None:
            ui.info("no pending subgoal to mark done")
            return ""
        pending.done = True
        save_state(pdir, state)
        agent.reload_goal()
        ui.info(f"subgoal done: {pending.text}")
        return ""

    # Anything else is a new subgoal text — append.
    state.subgoals.append(Subgoal(text=arg))
    save_state(pdir, state)
    agent.reload_goal()
    ui.info(f"subgoal added: {arg}")
    return ""
