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


def format_for_system_prompt(goal: str) -> str:
    """Return the block to append at the end of the system prompt."""
    return f"{GOAL_HEADER}\n\n{goal.strip()}"
