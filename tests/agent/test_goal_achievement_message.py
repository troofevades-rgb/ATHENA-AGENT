"""The ``Goal achieved`` stop-line distinguishes verified from
self-declared completions.

Without this, a model saying GOAL ACHIEVED with no verifier looks
identical on the screen to a real check passing. That ambiguity made
a Phase-3 test failure (misplaced TOML key → verifier never ran) look
like a successful run. Surface the gap explicitly.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _stub_agent(verifier_command):
    """Build a minimal stub of the bits ``_consult_goal_continuation``
    touches. We're testing only the achievement-message branch —
    everything else is mocked."""
    agent = MagicMock()
    agent.cfg = SimpleNamespace(
        goal_verifier_command=verifier_command,
        goal_max_tokens=0,  # disable token cap so we hit the goal hook
        goal_loop_enabled=True,
    )
    agent.goal_state = SimpleNamespace(turns_taken=3, max_turns=25)
    agent._profile_dir = MagicMock(return_value="/tmp")
    agent._last_assistant_text = "done\nGOAL ACHIEVED"
    agent._last_turn_interrupted = False
    agent._goal_loop_tokens_used = 0
    agent.stats = SimpleNamespace(
        prompt_tokens=0, eval_tokens=0,
    )
    return agent


def _achievement_branch_output(verifier_command):
    """Trigger the achievement branch via ``_consult_goal_continuation``
    and capture the printed line.

    We patch ``ui.console.print`` directly because rich's Console may
    route to either stdout or stderr depending on TTY detection, and
    we don't want the test to depend on that.
    """
    from athena.agent.core import Agent
    from athena.goal.loop import ContinuationDecision

    decision = ContinuationDecision(
        should_continue=False, stop_reason="achieved",
    )
    agent = _stub_agent(verifier_command)

    captured_lines: list[str] = []

    def _capture(*args, **kwargs):
        captured_lines.append(" ".join(str(a) for a in args))

    with patch(
        "athena.goal.loop.maybe_continue_goal_after_turn",
        return_value=decision,
    ), patch("athena.ui.console.print", side_effect=_capture):
        Agent._consult_goal_continuation(agent, tokens_at_loop_start=0)
    return "\n".join(captured_lines)


# ----------------------------------------------------------------------
# Verifier configured → message says "verifier passed"
# ----------------------------------------------------------------------


def test_achieved_with_verifier_says_verifier_passed():
    out = _achievement_branch_output("pytest -q")
    assert "Goal achieved" in out
    assert "verifier passed" in out
    # Ensure we did NOT also print the self-declared warning.
    assert "self-declared" not in out
    assert "no verifier configured" not in out


def test_achieved_with_complex_verifier_command_also_flagged():
    """Any truthy verifier_command counts as configured."""
    out = _achievement_branch_output(
        "pytest -q && mypy && ruff check .",
    )
    assert "verifier passed" in out


# ----------------------------------------------------------------------
# Verifier NOT configured → message warns about self-declaration
# ----------------------------------------------------------------------


def test_achieved_without_verifier_warns_self_declared():
    out = _achievement_branch_output(None)
    assert "Goal achieved" in out
    assert "self-declared" in out
    assert "no verifier configured" in out
    # Points at the fix.
    assert "goal_verifier_command" in out
    # Ensure we did NOT also print the verified message.
    assert "verifier passed" not in out


def test_achieved_with_empty_string_verifier_treated_as_unset():
    """An empty string verifier_command means no verifier — same as None."""
    out = _achievement_branch_output("")
    assert "self-declared" in out
    assert "verifier passed" not in out
