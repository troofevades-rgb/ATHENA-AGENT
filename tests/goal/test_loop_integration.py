"""Tests for the agent-core continuation loop integration (T5-07.5).

Drives :meth:`Agent._consult_goal_continuation` directly against
a minimal agent-shaped namespace. The full Agent constructor is
too heavy (credentials, providers, session store) and the
continuation hook itself doesn't depend on any of that — just on
``goal_state``, ``_last_assistant_text``, ``_last_turn_interrupted``,
``stats``, ``cfg``, and the profile dir.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.agent.core import Agent
from athena.goal.state import GoalState, load_state


def _cfg(**overrides) -> SimpleNamespace:
    base = {
        "goal_loop_enabled": True,
        "goal_max_turns": 25,
        "goal_max_tokens": 200_000,
        "goal_continuation_prompt": None,
        "goal_achieved_sentinel": "GOAL ACHIEVED",
        "goal_blocked_sentinel": "GOAL BLOCKED",
        "profile": "default",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _stats(prompt: int = 0, eval_: int = 0) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=prompt, eval_tokens=eval_)


def _agent(
    *,
    tmp_path: Path,
    goal_state: GoalState | None,
    assistant_text: str = "",
    interrupted: bool = False,
    cfg: SimpleNamespace | None = None,
    stats: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Compose a stub agent matching what _consult_goal_continuation reads."""
    a = SimpleNamespace(
        cfg=cfg if cfg is not None else _cfg(),
        stats=stats if stats is not None else _stats(),
        goal_state=goal_state,
        _last_assistant_text=assistant_text,
        _last_turn_interrupted=interrupted,
        _goal_loop_tokens_used=0,
    )
    a._profile_dir = lambda: tmp_path  # type: ignore[assignment]
    # Bind the real methods to the stub.
    a._consult_goal_continuation = (
        Agent._consult_goal_continuation.__get__(a)
    )
    a._persist_goal_state = Agent._persist_goal_state.__get__(a)
    return a


# ---------------------------------------------------------------------------
# Achievement / blocked / exhausted (turn cap)
# ---------------------------------------------------------------------------


def test_achieved_stops_loop(tmp_path: Path):
    st = GoalState(text="x")
    a = _agent(tmp_path=tmp_path, goal_state=st, assistant_text="GOAL ACHIEVED")
    assert a._consult_goal_continuation(tokens_at_loop_start=0) is None
    assert st.status == "achieved"
    persisted = load_state(tmp_path)
    assert persisted is not None
    assert persisted.status == "achieved"


def test_blocked_stops_loop_and_surfaces_reason(tmp_path: Path):
    st = GoalState(text="x")
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="GOAL BLOCKED: need creds",
    )
    assert a._consult_goal_continuation(tokens_at_loop_start=0) is None
    assert st.status == "paused"


def test_continuation_enqueues_synthetic_turn(tmp_path: Path):
    st = GoalState(text="x", max_turns=5)
    a = _agent(tmp_path=tmp_path, goal_state=st, assistant_text="working...")
    next_input = a._consult_goal_continuation(tokens_at_loop_start=0)
    assert next_input is not None
    assert "GOAL ACHIEVED" in next_input  # default continuation prompt
    assert st.turns_taken == 1


def test_exhaustion_at_turn_cap_stops_and_messages(tmp_path: Path):
    st = GoalState(text="x", max_turns=1)
    a = _agent(tmp_path=tmp_path, goal_state=st, assistant_text="working")
    assert a._consult_goal_continuation(tokens_at_loop_start=0) is None
    assert st.status == "exhausted"
    persisted = load_state(tmp_path)
    assert persisted is not None
    assert persisted.status == "exhausted"


# ---------------------------------------------------------------------------
# Interrupts always win
# ---------------------------------------------------------------------------


def test_ctrl_c_pauses_goal(tmp_path: Path):
    """T5-07 invariant: Ctrl+C pauses the goal — the loop never
    re-injects a synthetic turn after an interrupt."""
    st = GoalState(text="x", max_turns=10)
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="GOAL ACHIEVED",  # would normally stop on achieved
        interrupted=True,
    )
    next_input = a._consult_goal_continuation(tokens_at_loop_start=0)
    assert next_input is None
    assert st.status == "paused"
    # Persisted, not "achieved" (interrupt wins).
    persisted = load_state(tmp_path)
    assert persisted is not None
    assert persisted.status == "paused"


def test_interrupt_wins_over_active_continuation(tmp_path: Path):
    """Interrupt mid-continuation → pause, even though the model
    would have produced a continue-able assistant turn."""
    st = GoalState(text="x", max_turns=10)
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="still working...",
        interrupted=True,
    )
    next_input = a._consult_goal_continuation(tokens_at_loop_start=0)
    assert next_input is None
    assert st.status == "paused"
    # turns_taken NOT bumped — the interrupted turn doesn't count.
    assert st.turns_taken == 0


# ---------------------------------------------------------------------------
# Token cap
# ---------------------------------------------------------------------------


def test_token_cap_exhausts(tmp_path: Path):
    """Tokens used since loop start > goal_max_tokens → exhausted."""
    st = GoalState(text="x", max_turns=100)
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="working",
        cfg=_cfg(goal_max_tokens=1000),
        stats=_stats(prompt=900, eval_=200),  # 1100 > 1000
    )
    next_input = a._consult_goal_continuation(tokens_at_loop_start=0)
    assert next_input is None
    assert st.status == "exhausted"


def test_token_cap_with_loop_start_offset(tmp_path: Path):
    """The cap measures tokens since the loop began — pre-existing
    stats don't count against the budget."""
    st = GoalState(text="x", max_turns=100)
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="working",
        cfg=_cfg(goal_max_tokens=1000),
        stats=_stats(prompt=5000, eval_=200),  # 5200 total
    )
    # But the loop started at 5100 → this iteration used 100 → under cap
    next_input = a._consult_goal_continuation(tokens_at_loop_start=5100)
    assert next_input is not None  # continue
    assert st.turns_taken == 1


def test_token_cap_zero_means_disabled(tmp_path: Path):
    """goal_max_tokens=0 disables the token cap — only the turn
    cap applies."""
    st = GoalState(text="x", max_turns=10)
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="working",
        cfg=_cfg(goal_max_tokens=0),
        stats=_stats(prompt=10_000_000, eval_=10_000_000),  # absurd
    )
    next_input = a._consult_goal_continuation(tokens_at_loop_start=0)
    assert next_input is not None  # under disabled cap


# ---------------------------------------------------------------------------
# State guards
# ---------------------------------------------------------------------------


def test_no_state_no_continuation(tmp_path: Path):
    a = _agent(tmp_path=tmp_path, goal_state=None, assistant_text="anything")
    assert a._consult_goal_continuation(tokens_at_loop_start=0) is None


def test_paused_state_stops_without_announce(tmp_path: Path):
    """A user who paused via /goal pause shouldn't see another
    continuation, and the loop shouldn't print "exhausted" or
    "achieved"."""
    st = GoalState(text="x", status="paused", max_turns=10)
    a = _agent(tmp_path=tmp_path, goal_state=st, assistant_text="...")
    assert a._consult_goal_continuation(tokens_at_loop_start=0) is None
    # No mutation — state was already paused.
    assert st.status == "paused"
    assert st.turns_taken == 0


def test_disabled_loop_does_not_continue(tmp_path: Path):
    st = GoalState(text="x", max_turns=10)
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="working",
        cfg=_cfg(goal_loop_enabled=False),
    )
    assert a._consult_goal_continuation(tokens_at_loop_start=0) is None
    # Disabled is a hard short-circuit upstream — no turn bump.
    assert st.turns_taken == 0


# ---------------------------------------------------------------------------
# _goal_loop_tokens_used tracking
# ---------------------------------------------------------------------------


def test_loop_tokens_used_updated(tmp_path: Path):
    """The running token counter on self mirrors what was used
    since loop start — visible in /goal status downstream."""
    st = GoalState(text="x", max_turns=10)
    a = _agent(
        tmp_path=tmp_path,
        goal_state=st,
        assistant_text="working",
        stats=_stats(prompt=300, eval_=200),
    )
    a._consult_goal_continuation(tokens_at_loop_start=100)
    assert a._goal_loop_tokens_used == 400  # 500 - 100
