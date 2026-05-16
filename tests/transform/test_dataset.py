"""SFT + DPO dataset construction and JSONL serialization."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocode.transform.classifier import Trajectory
from ocode.transform.dataset import (
    build_dpo_dataset,
    build_sft_dataset,
    write_jsonl,
)


def _traj(
    *turns,
    session_id="s1",
    user_label="good",
    auto_label="unreviewed",
) -> Trajectory:
    return Trajectory(
        session_id=session_id,
        turn_start=0,
        turn_end=len(turns) - 1,
        turns=list(turns),
        user_label=user_label,
        auto_label=auto_label,
    )


# ---- SFT ---------------------------------------------------------------


def test_sft_dataset_format():
    t = _traj(
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    )
    examples = build_sft_dataset([t])
    assert len(examples) == 1
    ex = examples[0]
    assert "messages" in ex and "metadata" in ex
    assert ex["messages"][0] == {"role": "user", "content": "hi"}
    assert ex["messages"][1]["role"] == "assistant"
    assert ex["metadata"]["session_id"] == "s1"
    assert ex["metadata"]["turn_range"] == [0, 1]
    assert ex["metadata"]["chat_template"] == "qwen-coder"
    assert ex["metadata"]["label_source"] == "user"


def test_sft_includes_only_good_trajectories():
    good = _traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
        user_label="good",
    )
    bad = _traj(
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        user_label="bad",
    )
    unreviewed = _traj(
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
        user_label="unreviewed",
    )
    pref = _traj(
        {"role": "user", "content": "q4"},
        {"role": "assistant", "content": "a4"},
        user_label="preference_pair",
    )
    out = build_sft_dataset([good, bad, unreviewed, pref])
    assert len(out) == 1
    assert out[0]["messages"][0]["content"] == "q"


def test_sft_include_auto_labels_opt_in():
    auto_good = _traj(
        {"role": "user", "content": "auto"},
        {"role": "assistant", "content": "ok"},
        user_label="unreviewed",
        auto_label="good",
    )
    user_good = _traj(
        {"role": "user", "content": "user"},
        {"role": "assistant", "content": "ok"},
        user_label="good",
    )
    # Default: only user-labeled.
    out = build_sft_dataset([auto_good, user_good])
    assert len(out) == 1
    # With opt-in: both.
    out2 = build_sft_dataset([auto_good, user_good], include_auto_labels=True)
    assert len(out2) == 2
    labels = {e["metadata"]["label_source"] for e in out2}
    assert labels == {"user", "auto"}


def test_sft_user_label_overrides_auto_label():
    """A user explicitly set bad on an auto-labeled good trajectory →
    even with include_auto_labels, it should not appear."""
    t = _traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
        user_label="bad",
        auto_label="good",
    )
    assert build_sft_dataset([t], include_auto_labels=True) == []


def test_sft_steer_messages_normalized_to_plain_user_prompts():
    t = _traj(
        {"role": "user", "content": "do work"},
        {"role": "user", "content": "[/steer] focus on tests"},
        {"role": "assistant", "content": "ok"},
    )
    out = build_sft_dataset([t])
    msgs = out[0]["messages"]
    # The steer turn is now a plain user turn with the tag stripped.
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "focus on tests"
    assert "[/steer]" not in msgs[1]["content"]


def test_sft_tool_calls_normalized_to_canonical_shape():
    t = _traj(
        {"role": "user", "content": "read x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "Read", "arguments": {"path": "/tmp/x"}}}
            ],
        },
        {"role": "tool", "name": "Read", "content": "file contents"},
        {"role": "assistant", "content": "done"},
    )
    out = build_sft_dataset([t])
    asst = out[0]["messages"][1]
    assert asst["tool_calls"][0]["function"]["name"] == "Read"
    # Arguments dict → JSON string (qwen-coder convention).
    assert isinstance(asst["tool_calls"][0]["function"]["arguments"], str)
    assert json.loads(asst["tool_calls"][0]["function"]["arguments"]) == {
        "path": "/tmp/x"
    }


def test_sft_rejects_unknown_chat_template():
    t = _traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    )
    with pytest.raises(ValueError, match="unsupported chat_template"):
        build_sft_dataset([t], chat_template="not-real")


# ---- DPO ---------------------------------------------------------------


def test_dpo_dataset_format():
    chosen = _traj(
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "done correctly"},
    )
    rejected = _traj(
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "done incorrectly"},
        session_id="s2",
    )
    out = build_dpo_dataset([(chosen, rejected)])
    assert len(out) == 1
    ex = out[0]
    assert ex["prompt"] == "do it"
    assert ex["chosen"] == "done correctly"
    assert ex["rejected"] == "done incorrectly"
    assert ex["metadata"]["chosen_session_id"] == "s1"
    assert ex["metadata"]["rejected_session_id"] == "s2"


def test_dpo_requires_pairs():
    """Empty input → empty output, no exception."""
    assert build_dpo_dataset([]) == []


def test_dpo_drops_identical_chosen_rejected():
    """Pairs where the response text is identical don't carry signal."""
    chosen = _traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "same answer"},
    )
    rejected = _traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "same answer"},
    )
    assert build_dpo_dataset([(chosen, rejected)]) == []


def test_dpo_includes_tool_calls_in_response_text():
    chosen = _traj(
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [{"function": {"name": "Read", "arguments": {"p": 1}}}],
        },
        {"role": "tool", "name": "Read", "content": "ok"},
        {"role": "assistant", "content": "done"},
    )
    rejected = _traj(
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "no answer"},
        session_id="s2",
    )
    out = build_dpo_dataset([(chosen, rejected)])
    assert "<tool_call>" in out[0]["chosen"]
    assert "Read" in out[0]["chosen"]


# ---- write_jsonl -------------------------------------------------------


def test_write_jsonl_one_object_per_line(tmp_path: Path):
    target = tmp_path / "out.jsonl"
    write_jsonl(
        target,
        [{"messages": [{"role": "user", "content": "a"}]},
         {"messages": [{"role": "user", "content": "b"}]}],
    )
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["messages"][0]["content"] == "a"
    assert parsed[1]["messages"][0]["content"] == "b"


def test_write_jsonl_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "out.jsonl"
    write_jsonl(target, [{"x": 1}])
    assert target.exists()


def test_write_jsonl_overwrites_existing(tmp_path: Path):
    target = tmp_path / "out.jsonl"
    write_jsonl(target, [{"v": 1}, {"v": 2}])
    write_jsonl(target, [{"v": 3}])
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["v"] == 3
