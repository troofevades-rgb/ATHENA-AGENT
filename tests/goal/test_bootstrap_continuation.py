"""Tests for the auto-bootstrap continuation prompt returned by
``cmd_goal`` after ``/goal <text>`` and ``/goal resume``.

The slash-command dispatcher (``athena/__main__.py:_handle_slash``)
takes any non-empty string a command returns and runs it as a user
turn. ``cmd_goal`` used to return ``""`` unconditionally, leaving the
goal loop dormant until the user typed something. Now it returns the
continuation kicker so the model starts working immediately.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from athena.commands.goal import cmd_goal
from athena.goal.state import GoalState, save_state


class _StubAgent:
    def __init__(self, profile_dir: Path, max_turns: int = 25):
        self._pdir = profile_dir
        self.cfg = SimpleNamespace(
            goal_max_turns=max_turns,
            goal_continuation_prompt=None,
        )
        self.reload_called = 0

    def _profile_dir(self):
        return self._pdir

    def reload_goal(self):
        self.reload_called += 1


# ----------------------------------------------------------------------
# /goal <text> bootstraps
# ----------------------------------------------------------------------


def test_goal_set_returns_bootstrap_prompt(tmp_path: Path):
    a = _StubAgent(tmp_path)
    out = cmd_goal(a, "ship the migration verify command")
    assert isinstance(out, str)
    assert out != ""
    # The default prompt mentions GOAL ACHIEVED + the "one step" guidance.
    assert "GOAL ACHIEVED" in out
    assert "step" in out.lower()


def test_goal_set_uses_configured_continuation_prompt(tmp_path: Path):
    a = _StubAgent(tmp_path)
    a.cfg.goal_continuation_prompt = "CUSTOM KICKER"
    out = cmd_goal(a, "ship the migration verify command")
    assert out == "CUSTOM KICKER"


# ----------------------------------------------------------------------
# /goal resume bootstraps
# ----------------------------------------------------------------------


def test_goal_resume_returns_bootstrap_prompt(tmp_path: Path):
    save_state(
        tmp_path,
        GoalState(text="x", status="paused", turns_taken=5, max_turns=25),
    )
    a = _StubAgent(tmp_path)
    out = cmd_goal(a, "resume")
    assert out != ""
    assert "GOAL ACHIEVED" in out


def test_goal_resume_after_exhausted_bootstraps(tmp_path: Path):
    """The exact case from the user's session — exhausted → resume."""
    save_state(
        tmp_path,
        GoalState(text="x", status="exhausted", turns_taken=25, max_turns=25),
    )
    a = _StubAgent(tmp_path)
    out = cmd_goal(a, "resume")
    assert out != ""


def test_goal_resume_with_no_state_returns_empty(tmp_path: Path):
    """No state file → no goal to resume → no bootstrap."""
    a = _StubAgent(tmp_path)
    out = cmd_goal(a, "resume")
    assert out == ""


# ----------------------------------------------------------------------
# Other subcommands stay silent (return "")
# ----------------------------------------------------------------------


def test_goal_pause_returns_empty(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "a concrete test fixture goal")  # set first
    out = cmd_goal(a, "pause")
    assert out == ""


def test_goal_clear_returns_empty(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "a concrete test fixture goal")
    out = cmd_goal(a, "clear")
    assert out == ""


def test_goal_status_returns_empty(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "a concrete test fixture goal")
    out = cmd_goal(a, "status")
    assert out == ""


def test_bare_goal_returns_empty(tmp_path: Path):
    a = _StubAgent(tmp_path)
    cmd_goal(a, "a concrete test fixture goal")
    out = cmd_goal(a, "")
    assert out == ""
