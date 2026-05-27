"""``goal_verifier_command`` gates GOAL ACHIEVED on a real check.

The model self-declaring "done" is too cheap. When a verifier command
is configured, the loop runs it after the sentinel fires; a non-zero
exit refuses the achievement and feeds the output back to the model.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.goal.loop import (
    VerifierResult,
    maybe_continue_goal_after_turn,
    run_goal_verifier,
)
from athena.goal.state import GoalState


def _active_state(text: str = "Implement website_policy") -> GoalState:
    return GoalState(
        text=text,
        status="active",
        turns_taken=5,
        max_turns=25,
        goal_id="g-test",
        subgoals=[],
    )


def _cfg(**kwargs):
    base = dict(
        goal_loop_enabled=True,
        goal_continuation_prompt=None,
        goal_verifier_command=None,
        goal_verifier_timeout_s=10.0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


# ----------------------------------------------------------------------
# run_goal_verifier — direct unit tests
# ----------------------------------------------------------------------


def test_no_command_returns_none():
    """Without a configured verifier, run_goal_verifier returns None
    so the caller knows to accept the model's claim at face value."""
    assert run_goal_verifier(_cfg(goal_verifier_command=None)) is None
    assert run_goal_verifier(_cfg(goal_verifier_command="")) is None


def test_zero_exit_passes(monkeypatch):
    completed = subprocess.CompletedProcess(
        args="true", returncode=0, stdout="ok\n", stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: completed)
    result = run_goal_verifier(_cfg(goal_verifier_command="true"))
    assert result is not None
    assert result.passed is True
    assert "ok" in result.output


def test_nonzero_exit_fails(monkeypatch):
    completed = subprocess.CompletedProcess(
        args="false", returncode=1,
        stdout="FAIL: 2 tests broke\n", stderr="AssertionError\n",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: completed)
    result = run_goal_verifier(_cfg(goal_verifier_command="false"))
    assert result is not None
    assert result.passed is False
    assert "FAIL: 2 tests broke" in result.output
    assert "AssertionError" in result.output


def test_timeout_fails_with_reason(monkeypatch):
    def _raise(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="x", timeout=10)
    monkeypatch.setattr(subprocess, "run", _raise)
    result = run_goal_verifier(_cfg(goal_verifier_command="sleep 999"))
    assert result is not None
    assert result.passed is False
    assert "timed out" in result.output.lower()


def test_spawn_failure_fails_with_reason(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("no such file")
    monkeypatch.setattr(subprocess, "run", _raise)
    result = run_goal_verifier(_cfg(goal_verifier_command="missing-binary"))
    assert result is not None
    assert result.passed is False
    assert "failed to spawn" in result.output.lower()


def test_long_output_is_truncated(monkeypatch):
    big = "X" * 10_000
    completed = subprocess.CompletedProcess(
        args="cmd", returncode=1, stdout=big, stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: completed)
    result = run_goal_verifier(_cfg(goal_verifier_command="cmd"))
    assert result is not None
    assert "truncated" in result.output


# ----------------------------------------------------------------------
# maybe_continue_goal_after_turn — verifier integration
# ----------------------------------------------------------------------


def test_achieved_with_no_verifier_accepts(tmp_path: Path):
    state = _active_state()
    cfg = _cfg(goal_verifier_command=None)
    decision = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=state,
        last_assistant_text="Looks good.\nGOAL ACHIEVED",
        cfg=cfg,
    )
    assert decision.should_continue is False
    assert decision.stop_reason == "achieved"
    assert state.status == "achieved"


def test_achieved_with_passing_verifier_accepts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "athena.goal.loop.run_goal_verifier",
        lambda cfg: VerifierResult(passed=True, output="all green"),
    )
    state = _active_state()
    cfg = _cfg(goal_verifier_command="pytest")
    decision = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=state,
        last_assistant_text="Done.\nGOAL ACHIEVED",
        cfg=cfg,
    )
    assert decision.should_continue is False
    assert decision.stop_reason == "achieved"
    assert state.status == "achieved"


def test_achieved_with_failing_verifier_refuses(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "athena.goal.loop.run_goal_verifier",
        lambda cfg: VerifierResult(
            passed=False, output="FAILED tests/foo.py::test_bar",
        ),
    )
    state = _active_state()
    cfg = _cfg(goal_verifier_command="pytest")
    decision = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=state,
        last_assistant_text="Should be done now.\nGOAL ACHIEVED",
        cfg=cfg,
    )
    # Loop continues — goal is NOT achieved.
    assert decision.should_continue is True
    assert state.status == "active"
    # Verifier output reaches the model in the next synthetic prompt.
    assert decision.synthetic_prompt is not None
    assert "FAILED tests/foo.py::test_bar" in decision.synthetic_prompt
    assert "rejected by the verifier" in decision.synthetic_prompt
    assert "Do not re-emit GOAL ACHIEVED" in decision.synthetic_prompt


def test_failing_verifier_bumps_turns_taken(tmp_path: Path, monkeypatch):
    """A rejected achievement DOES count as a turn — turn-cap pressure
    is the only thing preventing a model that keeps claiming done
    from looping forever. The model spent a turn making the claim;
    it's fair to count it."""
    monkeypatch.setattr(
        "athena.goal.loop.run_goal_verifier",
        lambda cfg: VerifierResult(passed=False, output="nope"),
    )
    state = _active_state()
    turns_before = state.turns_taken
    maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=state,
        last_assistant_text="GOAL ACHIEVED",
        cfg=_cfg(goal_verifier_command="pytest"),
    )
    assert state.turns_taken == turns_before + 1


def test_failing_verifier_at_turn_cap_exhausts(tmp_path: Path, monkeypatch):
    """If the rejection bump would push turns_taken past max_turns, the
    loop must exhaust rather than spinning forever. A model stuck in
    the GOAL-ACHIEVED-rejection cycle needs a hard backstop."""
    monkeypatch.setattr(
        "athena.goal.loop.run_goal_verifier",
        lambda cfg: VerifierResult(passed=False, output="nope"),
    )
    state = _active_state()
    state.turns_taken = state.max_turns - 1  # one bump from exhaustion
    decision = maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=state,
        last_assistant_text="GOAL ACHIEVED",
        cfg=_cfg(goal_verifier_command="pytest"),
    )
    assert decision.should_continue is False
    assert decision.stop_reason == "exhausted"
    assert state.status == "exhausted"


def test_failing_verifier_emits_visible_ui_warn(tmp_path: Path, monkeypatch):
    """The rejection synthetic prompt goes to the MODEL only — the
    operator sees nothing unless we also print a UI message. Verify
    ui.warn fires when the verifier rejects."""
    monkeypatch.setattr(
        "athena.goal.loop.run_goal_verifier",
        lambda cfg: VerifierResult(
            passed=False, output="FAIL: 3 tests broke",
        ),
    )

    captured: list[str] = []
    monkeypatch.setattr(
        "athena.ui.warn", lambda msg, *a, **kw: captured.append(str(msg)),
    )

    state = _active_state()
    maybe_continue_goal_after_turn(
        profile_dir=tmp_path,
        state=state,
        last_assistant_text="GOAL ACHIEVED",
        cfg=_cfg(goal_verifier_command="pytest"),
    )
    # One visible warn fired with the verifier's first output line.
    assert len(captured) == 1
    assert "verifier rejected" in captured[0].lower()
    assert "FAIL: 3 tests broke" in captured[0]
