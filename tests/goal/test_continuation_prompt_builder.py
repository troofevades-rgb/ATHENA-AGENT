"""``build_continuation_prompt`` — state-aware kicker injected on every
synthetic turn. Tests the rendering rules: goal text always present,
turn counter always present, subgoal next-step surfaced when set,
auto-decompose hint when not.
"""

from __future__ import annotations

from types import SimpleNamespace

from athena.goal.loop import build_continuation_prompt
from athena.goal.state import GoalState, Subgoal


def _state(text: str = "Port website_policy", **overrides) -> GoalState:
    base = dict(
        text=text,
        status="active",
        turns_taken=3,
        max_turns=25,
        goal_id="g-test",
        subgoals=[],
    )
    base.update(overrides)
    return GoalState(**base)


# ----------------------------------------------------------------------
# Always-present fields
# ----------------------------------------------------------------------


def test_includes_goal_text():
    out = build_continuation_prompt(_state("Port hermes website_policy"))
    assert "Goal: Port hermes website_policy" in out


def test_includes_turn_counter():
    out = build_continuation_prompt(_state(turns_taken=7, max_turns=100))
    assert "turn 7/100" in out


def test_always_repeats_sentinel_contract():
    out = build_continuation_prompt(_state())
    assert "GOAL ACHIEVED" in out
    assert "GOAL BLOCKED" in out


# ----------------------------------------------------------------------
# Subgoal-aware rendering
# ----------------------------------------------------------------------


def test_no_subgoals_nudges_decomposition():
    """The auto-decompose hint — the first thing the model should do
    on a multi-step goal is /subgoal it down."""
    out = build_continuation_prompt(_state(subgoals=[]))
    assert "decompose" in out.lower()
    assert "/subgoal" in out


def test_pending_subgoal_surfaced_explicitly():
    state = _state(subgoals=[
        Subgoal(text="Write the policy module", done=False),
        Subgoal(text="Add the @tool wrapper", done=False),
    ])
    out = build_continuation_prompt(state)
    assert "Next subgoal: Write the policy module" in out


def test_done_subgoals_summarized():
    state = _state(subgoals=[
        Subgoal(text="Read the hermes source", done=True),
        Subgoal(text="Write the policy module", done=False),
    ])
    out = build_continuation_prompt(state)
    assert "Read the hermes source" in out
    assert "Next subgoal: Write the policy module" in out


def test_all_subgoals_done_prompts_verification():
    state = _state(subgoals=[
        Subgoal(text="First step", done=True),
        Subgoal(text="Second step", done=True),
    ])
    out = build_continuation_prompt(state)
    assert "subgoals are done" in out.lower()
    # Sentinel reminder still present so the model knows how to finish.
    assert "GOAL ACHIEVED" in out


def test_many_pending_subgoals_shows_next_three():
    """Surface the next subgoal explicitly + a 'then' list of the
    following few so the model can plan ahead."""
    state = _state(subgoals=[
        Subgoal(text=f"step {i}", done=False) for i in range(6)
    ])
    out = build_continuation_prompt(state)
    assert "Next subgoal: step 0" in out
    assert "step 1" in out
    assert "step 2" in out


# ----------------------------------------------------------------------
# Override + fallback
# ----------------------------------------------------------------------


def test_cfg_override_wins():
    cfg = SimpleNamespace(goal_continuation_prompt="CUSTOM KICKER")
    out = build_continuation_prompt(_state(), cfg=cfg)
    assert out == "CUSTOM KICKER"


def test_none_cfg_falls_through():
    """Missing cfg attribute is fine — falls back to built-in builder."""
    out = build_continuation_prompt(_state(), cfg=None)
    assert "GOAL ACHIEVED" in out


def test_none_state_falls_back_to_bare_kicker():
    """If state isn't available yet (rare edge case), still return a
    usable prompt — the legacy one-liner."""
    out = build_continuation_prompt(None)
    assert "GOAL ACHIEVED" in out
    # No state-specific fields when state is None.
    assert "Next subgoal" not in out
    assert "Progress: turn" not in out
