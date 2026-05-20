"""``/goal`` — persistent invariant injected into every prompt rebuild.

A goal is a single short string the user wants the agent to keep in mind
across every turn. Stored as ``<profile_dir>/goal.txt`` so it survives
restarts. Loaded once at session start and re-injected on every system
prompt rebuild (e.g. after ``/cwd`` or ``/clear``).

Goal changes do NOT affect history. Past assistant turns made under a
prior goal are not re-evaluated; the goal only governs subsequent
decisions.
"""

from __future__ import annotations

from pathlib import Path

GOAL_FILENAME = "goal.txt"
GOAL_HEADER = "## Current goal (invariant — keep in mind during every action)"


def goal_path(profile_dir: Path) -> Path:
    return profile_dir / GOAL_FILENAME


def get_goal(profile_dir: Path) -> str | None:
    """Read the persisted goal, or ``None`` if absent / empty / unreadable."""
    p = goal_path(profile_dir)
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def set_goal(profile_dir: Path, goal: str) -> Path:
    """Persist ``goal`` for the profile. Strips whitespace; rejects empty."""
    goal = goal.strip()
    if not goal:
        raise ValueError("goal must not be empty")
    p = goal_path(profile_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(goal + "\n", encoding="utf-8")
    return p


def clear_goal(profile_dir: Path) -> bool:
    """Remove the goal file. Returns ``True`` if a goal was present."""
    p = goal_path(profile_dir)
    if not p.exists():
        return False
    p.unlink()
    return True


def format_for_system_prompt(
    goal: str,
    *,
    state: "GoalState | None" = None,
) -> str:
    """Return the block to append at the end of the system prompt.

    When a :class:`athena.goal.state.GoalState` is provided
    (T5-07), the block also lists subgoals (ordered, with ✓ on
    done ones) and the sentinel contract that the continuation
    loop reads — telling the model how to signal achievement or
    blockage in its turn output.

    The block always starts with the goal text. Subgoals and the
    contract are appended only when they apply, so a goal set
    without subgoals (or with the loop disabled) still gets a
    clean, minimal block.
    """
    parts = [GOAL_HEADER, "", goal.strip()]

    if state is not None and state.subgoals:
        parts.append("")
        parts.append("**Subgoals** (ordered breadcrumbs; advisory):")
        for sg in state.subgoals:
            marker = "✓" if sg.done else "•"
            parts.append(f"  {marker} {sg.text}")

    if state is not None:
        parts.append("")
        parts.append(
            "**Loop contract**: when this goal is fully achieved, end "
            "your turn with a line containing exactly: `GOAL ACHIEVED`. "
            "If you are blocked and need the user, end with: "
            "`GOAL BLOCKED: <reason>`. The continuation loop reads "
            "these sentinels — they're how you tell the loop to stop."
        )

    return "\n".join(parts)
