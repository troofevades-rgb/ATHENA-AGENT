"""Goal-quality gate — refuse aspirational/vague goal text.

Without this, the model spends entire sessions wandering on goals
like 'be the best agent'. Making the user phrase a concrete
deliverable up front saves the wasted compute.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.commands.goal import _validate_goal_text, cmd_goal
from athena.goal.invariant import get_goal


class _StubAgent:
    def __init__(self, tmp_path: Path):
        self._pdir = tmp_path
        self.cfg = SimpleNamespace(
            goal_max_turns=25,
            goal_continuation_prompt=None,
        )
        self.reload_called = 0

    def _profile_dir(self):
        return self._pdir

    @property
    def provider(self):
        return None

    def reload_goal(self):
        self.reload_called += 1


# ----------------------------------------------------------------------
# _validate_goal_text — direct tests
# ----------------------------------------------------------------------


def test_validate_empty():
    assert _validate_goal_text("") == "Goal text required."


def test_validate_too_short():
    err = _validate_goal_text("do it")
    assert err is not None
    assert "too short" in err.lower()


def test_validate_three_words_rejected():
    err = _validate_goal_text("ship the code")
    assert err is not None
    assert "too short" in err.lower()


def test_validate_four_words_accepted_if_concrete():
    """4 words is the threshold — concrete tasks at that length pass."""
    assert _validate_goal_text("ship the migration verify command") is None


def test_validate_be_the_best_rejected():
    """The literal failure pattern from the user's session."""
    err = _validate_goal_text("be the best CLI agentic coder in the world")
    assert err is not None
    assert "ambition" in err.lower()


def test_validate_become_amazing_rejected():
    err = _validate_goal_text("become the most amazing agent ever built")
    assert err is not None
    assert "ambition" in err.lower()


def test_validate_do_everything_rejected():
    err = _validate_goal_text("do everything that I want to ship")
    assert err is not None
    assert "ambition" in err.lower()


def test_validate_make_perfect_rejected():
    err = _validate_goal_text("make the perfect testing framework here")
    assert err is not None


def test_validate_concrete_deliverable_accepted():
    """The error message's own example must pass its own check."""
    assert _validate_goal_text(
        "Ship the migration verify command with passing tests"
    ) is None


def test_validate_specific_port_task_accepted():
    assert _validate_goal_text(
        "Port hermes website_policy as athena/browser/policy.py"
    ) is None


def test_validate_case_insensitive():
    """'BE THE BEST' should also be rejected."""
    err = _validate_goal_text("BE THE BEST AGENT EVER BUILT FOR CODING")
    assert err is not None


# ----------------------------------------------------------------------
# /goal <text> integration — vague text → error, state not mutated
# ----------------------------------------------------------------------


def test_cmd_goal_rejects_vague_text(tmp_path: Path, capsys):
    a = _StubAgent(tmp_path)
    out = cmd_goal(a, "be the best ever")
    # Refused → no bootstrap prompt.
    assert out == ""
    # No goal.txt was written.
    assert get_goal(tmp_path) is None
    # reload_goal NOT called because the state didn't change.
    assert a.reload_called == 0


def test_cmd_goal_accepts_concrete_text(tmp_path: Path):
    a = _StubAgent(tmp_path)
    out = cmd_goal(a, "Implement the website_policy port with tests")
    # Accepted → bootstrap prompt returned for the dispatcher to fire.
    assert out != ""
    assert get_goal(tmp_path) == "Implement the website_policy port with tests"
    assert a.reload_called == 1
