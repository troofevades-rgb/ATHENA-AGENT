"""In-trajectory DPO extraction (the correct, default path).

Covers :func:`extract_steer_dpo_example` and
:func:`build_dpo_dataset_from_trajectories` — the replacement for the
unsafe cross-trajectory pairing that lived in ``cli/train.py``.
"""

from __future__ import annotations

import json

from athena.transform.classifier import Trajectory
from athena.transform.dataset import (
    FAILURE_MODES,
    build_dpo_dataset_from_trajectories,
    extract_steer_dpo_example,
)


def _pref_traj(*turns, session_id="s1") -> Trajectory:
    """Trajectory with ``user_label == "preference_pair"`` (the standard
    case for the new builder)."""
    return Trajectory(
        session_id=session_id,
        turn_start=0,
        turn_end=len(turns) - 1,
        turns=list(turns),
        user_label="preference_pair",
        auto_label="unreviewed",
    )


# ---- extract_steer_dpo_example: happy path -------------------------------


def test_steer_extract_clean_split():
    """Prompt → pre-steer assistant work (rejected) → [/steer] → recovery (chosen).
    Both branches share the same prompt, which is the whole point.
    """
    t = _pref_traj(
        {"role": "user", "content": "rename foo to bar in src/"},
        {"role": "assistant", "content": "I'll just rename the file."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "Bash", "arguments": {"cmd": "mv foo bar"}}}
            ],
        },
        {"role": "tool", "name": "Bash", "content": "ok"},
        {"role": "user", "content": "[/steer] no, I meant all references in the code"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "Grep", "arguments": {"pattern": "foo"}}}
            ],
        },
        {"role": "tool", "name": "Grep", "content": "src/a.py:1: foo"},
        {"role": "assistant", "content": "Updated 3 files."},
    )
    ex = extract_steer_dpo_example(t)
    assert ex is not None
    assert ex["prompt"] == "rename foo to bar in src/"
    assert "mv foo bar" in ex["rejected"]
    assert "Grep" in ex["chosen"]
    assert ex["chosen"] != ex["rejected"]
    # Metadata invariants
    assert ex["metadata"]["source"] == "steer_recovery"
    assert ex["metadata"]["session_id"] == "s1"
    assert ex["metadata"]["failure_mode"] in FAILURE_MODES


def test_steer_extract_failure_mode_wrong_tool():
    """Different tool at the same position → wrong_tool."""
    t = _pref_traj(
        {"role": "user", "content": "find the bug"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "Bash", "arguments": {"cmd": "ls"}}}],
        },
        {"role": "tool", "name": "Bash", "content": "ok"},
        {"role": "user", "content": "[/steer] grep instead"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "Grep", "arguments": {"pattern": "x"}}}],
        },
        {"role": "tool", "name": "Grep", "content": "found"},
        {"role": "assistant", "content": "done"},
    )
    ex = extract_steer_dpo_example(t)
    assert ex is not None
    assert ex["metadata"]["failure_mode"] == "wrong_tool"


def test_steer_extract_failure_mode_bad_args():
    """Same tool name, different arguments → bad_args."""
    t = _pref_traj(
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "Bash", "arguments": {"cmd": "ls /"}}}],
        },
        {"role": "tool", "name": "Bash", "content": "..."},
        {"role": "user", "content": "[/steer] I meant the current dir"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "Bash", "arguments": {"cmd": "ls ."}}}],
        },
        {"role": "tool", "name": "Bash", "content": "..."},
        {"role": "assistant", "content": "here"},
    )
    ex = extract_steer_dpo_example(t)
    assert ex is not None
    assert ex["metadata"]["failure_mode"] == "bad_args"


def test_steer_extract_failure_mode_format_error():
    """Malformed (non-JSON) tool-call arguments dominate other signals."""
    t = _pref_traj(
        {"role": "user", "content": "x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "Bash", "arguments": "this is not json {{"}}
            ],
        },
        {"role": "user", "content": "[/steer] valid json please"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "Bash", "arguments": {"cmd": "ls"}}}],
        },
        {"role": "tool", "name": "Bash", "content": "ok"},
        {"role": "assistant", "content": "done"},
    )
    ex = extract_steer_dpo_example(t)
    assert ex is not None
    assert ex["metadata"]["failure_mode"] == "format_error"


def test_steer_extract_failure_mode_tool_error():
    """Rejected branch hit a tool error and didn't recover before steer."""
    t = _pref_traj(
        {"role": "user", "content": "read config"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "Read", "arguments": {"path": "/etc/missing"}}}
            ],
        },
        {"role": "tool", "name": "Read", "content": "Error: file not found"},
        {"role": "user", "content": "[/steer] try the user dir"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "Read", "arguments": {"path": "~/.cfg"}}}
            ],
        },
        {"role": "tool", "name": "Read", "content": "ok"},
        {"role": "assistant", "content": "got it"},
    )
    ex = extract_steer_dpo_example(t)
    assert ex is not None
    assert ex["metadata"]["failure_mode"] == "tool_error"


def test_steer_extract_failure_mode_missing_tool():
    """Rejected made no tool calls; chosen used one."""
    t = _pref_traj(
        {"role": "user", "content": "what's in the file"},
        {"role": "assistant", "content": "I don't know without looking."},
        {"role": "user", "content": "[/steer] then look"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "Read", "arguments": {"path": "f.txt"}}}
            ],
        },
        {"role": "tool", "name": "Read", "content": "hello"},
        {"role": "assistant", "content": "it says hello"},
    )
    ex = extract_steer_dpo_example(t)
    assert ex is not None
    assert ex["metadata"]["failure_mode"] == "missing_tool"


# ---- extract_steer_dpo_example: drop cases -------------------------------


def test_steer_extract_no_steer_returns_none():
    t = _pref_traj(
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    )
    assert extract_steer_dpo_example(t) is None


def test_steer_extract_steer_at_end_returns_none():
    """Steer arrives with no following assistant work → no chosen branch."""
    t = _pref_traj(
        {"role": "user", "content": "do x"},
        {"role": "assistant", "content": "doing"},
        {"role": "user", "content": "[/steer] stop"},
    )
    assert extract_steer_dpo_example(t) is None


def test_steer_extract_steer_immediate_returns_none():
    """Steer arrives before any assistant work → no rejected branch."""
    t = _pref_traj(
        {"role": "user", "content": "do x"},
        {"role": "user", "content": "[/steer] wait actually do y"},
        {"role": "assistant", "content": "ok, y"},
    )
    assert extract_steer_dpo_example(t) is None


def test_steer_extract_identical_branches_returns_none():
    """If pre and post stringify to the same content, there's no signal."""
    t = _pref_traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "same"},
        {"role": "user", "content": "[/steer] try again"},
        {"role": "assistant", "content": "same"},
    )
    assert extract_steer_dpo_example(t) is None


def test_steer_extract_multiple_steers_splits_at_first():
    """First steer is the rejection point; later steers fold into the
    chosen recovery."""
    t = _pref_traj(
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "attempt 1"},
        {"role": "user", "content": "[/steer] no"},
        {"role": "assistant", "content": "attempt 2"},
        {"role": "user", "content": "[/steer] closer but"},
        {"role": "assistant", "content": "attempt 3 (correct)"},
    )
    ex = extract_steer_dpo_example(t)
    assert ex is not None
    assert "attempt 1" in ex["rejected"]
    assert "attempt 1" not in ex["chosen"]
    # Both later attempts land in the chosen branch.
    assert "attempt 2" in ex["chosen"]
    assert "attempt 3" in ex["chosen"]


def test_steer_extract_invalid_chat_template_raises():
    t = _pref_traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "[/steer] b"},
        {"role": "assistant", "content": "c"},
    )
    try:
        extract_steer_dpo_example(t, chat_template="nope")
    except ValueError as e:
        assert "chat_template" in str(e)
    else:
        raise AssertionError("expected ValueError")


# ---- build_dpo_dataset_from_trajectories ---------------------------------


def test_builder_filters_by_label():
    """Only ``preference_pair`` trajectories produce examples."""
    pref = _pref_traj(
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "wrong"},
        {"role": "user", "content": "[/steer] right"},
        {"role": "assistant", "content": "correct"},
    )
    good = Trajectory(
        session_id="s2",
        turn_start=0,
        turn_end=1,
        turns=[
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ],
        user_label="good",
    )
    out = build_dpo_dataset_from_trajectories([pref, good])
    assert len(out) == 1
    assert out[0]["metadata"]["session_id"] == "s1"


def test_builder_include_auto_labels():
    """Auto-labeled preference_pair trajectories opt in via flag only."""
    auto = Trajectory(
        session_id="s1",
        turn_start=0,
        turn_end=3,
        turns=[
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "wrong"},
            {"role": "user", "content": "[/steer] right"},
            {"role": "assistant", "content": "correct"},
        ],
        user_label="unreviewed",
        auto_label="preference_pair",
    )
    assert build_dpo_dataset_from_trajectories([auto]) == []
    out = build_dpo_dataset_from_trajectories([auto], include_auto_labels=True)
    assert len(out) == 1


def test_builder_user_label_overrides_auto():
    """If a human labeled the trajectory something else, auto-label is ignored."""
    overridden = Trajectory(
        session_id="s1",
        turn_start=0,
        turn_end=3,
        turns=[
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "wrong"},
            {"role": "user", "content": "[/steer] right"},
            {"role": "assistant", "content": "correct"},
        ],
        user_label="bad",  # human says no, drop this
        auto_label="preference_pair",
    )
    assert (
        build_dpo_dataset_from_trajectories([overridden], include_auto_labels=True) == []
    )


def test_builder_drops_unqualified_trajectories_silently():
    """Trajectories tagged preference_pair but with no extractable signal
    (e.g. no steer marker — possible if the label was set by hand)
    are silently skipped rather than raising."""
    nopref = _pref_traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    )
    pref = _pref_traj(
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "wrong"},
        {"role": "user", "content": "[/steer] right"},
        {"role": "assistant", "content": "correct"},
        session_id="s2",
    )
    out = build_dpo_dataset_from_trajectories([nopref, pref])
    assert len(out) == 1
    assert out[0]["metadata"]["session_id"] == "s2"


def test_builder_output_is_jsonl_safe():
    """Every example must round-trip through ``json.dumps`` cleanly so
    :func:`write_jsonl` won't choke on it downstream."""
    t = _pref_traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "wrong"},
        {"role": "user", "content": "[/steer] right"},
        {"role": "assistant", "content": "correct"},
    )
    out = build_dpo_dataset_from_trajectories([t])
    for ex in out:
        # Will raise TypeError if anything is non-serializable.
        json.dumps(ex, sort_keys=True)
