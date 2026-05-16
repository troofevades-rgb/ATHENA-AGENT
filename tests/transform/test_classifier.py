"""Trajectory extraction + auto-classification."""
from __future__ import annotations

import pytest

from ocode.transform.classifier import (
    Trajectory,
    auto_classify,
    extract_trajectories,
)


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant(text: str, tool_calls=None) -> dict:
    m: dict = {"role": "assistant", "content": text}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def _tool(name: str, content: str) -> dict:
    return {"role": "tool", "name": name, "content": content}


# ---- extract_trajectories ----------------------------------------------


def test_extract_trajectories_splits_correctly():
    """Two user turns each followed by a final assistant message → two trajectories."""
    messages = [
        {"role": "system", "content": "..."},
        _user("first question"),
        _assistant("first answer"),
        _user("second question"),
        _assistant("second answer"),
    ]
    trajs = extract_trajectories("s1", messages)
    assert len(trajs) == 2
    assert trajs[0].turn_start == 1 and trajs[0].turn_end == 2
    assert trajs[1].turn_start == 3 and trajs[1].turn_end == 4


def test_extract_includes_tool_calls_in_span():
    """A multi-round tool-using turn becomes a single trajectory."""
    messages = [
        _user("do work"),
        _assistant("calling", tool_calls=[{"function": {"name": "Read", "arguments": "{}"}}]),
        _tool("Read", "file contents"),
        _assistant("more", tool_calls=[{"function": {"name": "Edit", "arguments": "{}"}}]),
        _tool("Edit", "ok"),
        _assistant("final answer"),
    ]
    trajs = extract_trajectories("s1", messages)
    assert len(trajs) == 1
    assert len(trajs[0].turns) == 6  # whole span
    assert trajs[0].turns[-1]["content"] == "final answer"


def test_extract_skips_synthetic_steer_messages():
    """A [/steer] user message extends the prior turn, doesn't start a new one."""
    messages = [
        _user("original prompt"),
        _assistant("partial",
                   tool_calls=[{"function": {"name": "Read", "arguments": "{}"}}]),
        _tool("Read", "data"),
        {"role": "user", "content": "[/steer] focus on tests"},
        _assistant("recovered final response"),
    ]
    trajs = extract_trajectories("s1", messages)
    assert len(trajs) == 1
    # The steer message is part of the trajectory's span:
    assert any(
        isinstance(m.get("content"), str) and m["content"].startswith("[/steer]")
        for m in trajs[0].turns
    )


def test_extract_drops_unterminated_trajectory():
    """A user turn with no final assistant message is dropped."""
    messages = [
        _user("first"),
        _assistant("done"),
        _user("unfinished work"),
        _assistant("calling",
                   tool_calls=[{"function": {"name": "X", "arguments": "{}"}}]),
        _tool("X", "..."),
        # No final assistant message — turn interrupted.
    ]
    trajs = extract_trajectories("s1", messages)
    assert len(trajs) == 1
    assert trajs[0].turns[0]["content"] == "first"


def test_extract_empty_session():
    assert extract_trajectories("s1", []) == []


def test_extract_only_system_message():
    """System-only message list has no trajectories."""
    assert extract_trajectories("s1", [{"role": "system", "content": "..."}]) == []


# ---- auto_classify ------------------------------------------------------


def test_auto_classify_good_trajectory_via_positive_followup():
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=1,
        turns=[_user("q"), _assistant("a")],
    )
    label = auto_classify(traj, next_user_message=_user("thanks, perfect!"))
    assert label == "good"


def test_auto_classify_good_via_emoji_followup():
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=1,
        turns=[_user("q"), _assistant("a")],
    )
    label = auto_classify(traj, next_user_message=_user("👍"))
    assert label == "good"


def test_auto_classify_bad_trajectory_with_error_propagation():
    """Final tool result was an error → bad."""
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=3,
        turns=[
            _user("read x"),
            _assistant("", tool_calls=[{"function": {"name": "Read", "arguments": "{}"}}]),
            _tool("Read", "Error: file not found"),
            _assistant("I couldn't read it."),
        ],
    )
    assert auto_classify(traj) == "bad"


def test_auto_classify_bad_via_traceback_signature():
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=3,
        turns=[
            _user("run"),
            _assistant("", tool_calls=[{"function": {"name": "Bash", "arguments": "{}"}}]),
            _tool("Bash", "Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>"),
            _assistant("script failed"),
        ],
    )
    assert auto_classify(traj) == "bad"


def test_auto_classify_bad_via_negative_followup():
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=1,
        turns=[_user("q"), _assistant("a")],
    )
    label = auto_classify(traj, next_user_message=_user("no, that's wrong"))
    assert label == "bad"


def test_auto_classify_preference_pair_with_steer_recovery():
    """Trajectory with /steer mid-flight and a clean final answer."""
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=4,
        turns=[
            _user("original"),
            _assistant("", tool_calls=[{"function": {"name": "Read", "arguments": "{}"}}]),
            _tool("Read", "data"),
            {"role": "user", "content": "[/steer] focus on tests"},
            _assistant("recovered"),
        ],
    )
    assert auto_classify(traj) == "preference_pair"


def test_auto_classify_steer_without_recovery_falls_through():
    """A steer followed by a tool error doesn't count as recovery."""
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=5,
        turns=[
            _user("q"),
            {"role": "user", "content": "[/steer] try again"},
            _assistant("", tool_calls=[{"function": {"name": "Bash", "arguments": "{}"}}]),
            _tool("Bash", "Error: still broken"),
            _assistant("could not recover"),
        ],
    )
    # Last tool was error → bad, not preference_pair.
    assert auto_classify(traj) == "bad"


def test_auto_classify_returns_unreviewed_for_ambiguous():
    """No errors, no positive/negative follow-up → unreviewed."""
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=1,
        turns=[_user("q"), _assistant("a")],
    )
    assert auto_classify(traj) == "unreviewed"
    assert auto_classify(traj, next_user_message=_user("ok, next thing")) == "unreviewed"


def test_auto_classify_recovery_after_intermediate_error_still_good():
    """Tool errored, then assistant recovered with a successful tool, then
    finished. Last tool isn't an error → not bad."""
    traj = Trajectory(
        session_id="s",
        turn_start=0, turn_end=5,
        turns=[
            _user("read it"),
            _assistant("", tool_calls=[{"function": {"name": "Read", "arguments": "{}"}}]),
            _tool("Read", "Error: file not found"),
            _assistant("", tool_calls=[{"function": {"name": "Glob", "arguments": "{}"}}]),
            _tool("Glob", "file: /tmp/x.txt"),
            _assistant("found it: /tmp/x.txt"),
        ],
    )
    # Positive follow-up promotes to good. Without it, this is unreviewed
    # (no error in *last* tool, no /steer, no follow-up).
    label = auto_classify(traj, next_user_message=_user("perfect"))
    assert label == "good"
