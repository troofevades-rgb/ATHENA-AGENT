"""Tests for athena.transform.suggestion (T3-05R.4).

Verifies:

- classifier fallback when no metrics file exists (the hard
  requirement: T3-06 is optional)
- metrics override when the file is present and the skill has
  ≥ MIN_INVOCATIONS_FOR_OVERRIDE with ≥ OVERRIDE_THRESHOLD agreement
- skill name extraction from explicit metadata + tool_calls heuristic
"""

from __future__ import annotations

import json
from pathlib import Path

from athena.transform.classifier import Trajectory
from athena.transform.suggestion import (
    MIN_INVOCATIONS_FOR_OVERRIDE,
    OVERRIDE_THRESHOLD,
    build_suggestion_fn,
    extract_skill_name_from,
    metrics_override_for,
)


def _traj(
    auto: str = "unreviewed",
    *,
    skill_meta: str | None = None,
    skill_tool: str | None = None,
) -> Trajectory:
    turns = [{"role": "user", "content": "hi"}]
    if skill_tool is not None:
        turns.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": skill_tool, "arguments": "{}"}}],
            }
        )
    turns.append({"role": "assistant", "content": "done"})
    return Trajectory(
        session_id="s1",
        turn_start=0,
        turn_end=len(turns) - 1,
        turns=turns,
        auto_label=auto,  # type: ignore[arg-type]
        metadata={"skill_name": skill_meta} if skill_meta else {},
    )


def _write_metrics(profile_dir: Path, lines: list[dict]) -> None:
    path = profile_dir / "skill_metrics.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


# ---------------------------------------------------------------------------
# Hard requirement: works without metrics
# ---------------------------------------------------------------------------


def test_falls_back_to_classifier_without_metrics(tmp_path: Path) -> None:
    fn = build_suggestion_fn(tmp_path)  # no skill_metrics.jsonl
    sug = fn(_traj(auto="good"))
    assert sug is not None
    assert sug.label == "good"
    assert sug.source == "classifier"


def test_no_profile_dir_classifier_only() -> None:
    fn = build_suggestion_fn(None)
    sug = fn(_traj(auto="bad"))
    assert sug is not None
    assert sug.source == "classifier"
    assert sug.label == "bad"


def test_unreviewed_classifier_returns_none(tmp_path: Path) -> None:
    fn = build_suggestion_fn(tmp_path)
    assert fn(_traj(auto="unreviewed")) is None


def test_malformed_metrics_falls_back(tmp_path: Path) -> None:
    (tmp_path / "skill_metrics.jsonl").write_text("this is not json\n", encoding="utf-8")
    fn = build_suggestion_fn(tmp_path)
    sug = fn(_traj(auto="good"))
    assert sug is not None
    assert sug.source == "classifier"


# ---------------------------------------------------------------------------
# Metrics override
# ---------------------------------------------------------------------------


def test_metrics_boost_suggestion_when_present(tmp_path: Path) -> None:
    """≥ MIN_INVOCATIONS_FOR_OVERRIDE good labels at ≥ OVERRIDE_THRESHOLD
    agreement → override to good even if the classifier said
    unreviewed."""
    _write_metrics(
        tmp_path,
        [
            {"skill_name": "demo-skill", "good": 20, "bad": 0, "preference_pair": 0},
        ],
    )
    fn = build_suggestion_fn(tmp_path)
    sug = fn(_traj(auto="unreviewed", skill_meta="demo-skill"))
    assert sug is not None
    assert sug.label == "good"
    assert sug.source == "metrics"
    assert sug.confidence == 1.0


def test_metrics_override_bad_when_distribution_is_negative(tmp_path: Path) -> None:
    _write_metrics(
        tmp_path,
        [{"skill_name": "bad-skill", "good": 0, "bad": 15, "preference_pair": 0}],
    )
    fn = build_suggestion_fn(tmp_path)
    sug = fn(_traj(auto="unreviewed", skill_meta="bad-skill"))
    assert sug is not None
    assert sug.label == "bad"
    assert sug.source == "metrics"


def test_metrics_below_min_invocations_falls_back(tmp_path: Path) -> None:
    """Below MIN_INVOCATIONS_FOR_OVERRIDE the metrics signal is too
    noisy; classifier wins."""
    _write_metrics(
        tmp_path,
        [{"skill_name": "small-skill", "good": 2, "bad": 0, "preference_pair": 0}],
    )
    fn = build_suggestion_fn(tmp_path)
    sug = fn(_traj(auto="bad", skill_meta="small-skill"))
    assert sug is not None
    assert sug.label == "bad"  # classifier
    assert sug.source == "classifier"


def test_metrics_below_threshold_falls_back(tmp_path: Path) -> None:
    """≥ MIN_INVOCATIONS_FOR_OVERRIDE but below OVERRIDE_THRESHOLD → classifier wins."""
    _write_metrics(
        tmp_path,
        [{"skill_name": "borderline", "good": 12, "bad": 3, "preference_pair": 0}],
    )
    fn = build_suggestion_fn(tmp_path)
    sug = fn(_traj(auto="good", skill_meta="borderline"))
    assert sug.source == "classifier"
    assert sug.label == "good"


def test_metrics_only_apply_when_skill_known(tmp_path: Path) -> None:
    """An overriding distribution for skill A doesn't bleed into a
    trajectory that used skill B (or that we can't attribute)."""
    _write_metrics(
        tmp_path,
        [{"skill_name": "skillA", "good": 20, "bad": 0, "preference_pair": 0}],
    )
    fn = build_suggestion_fn(tmp_path)
    sug = fn(_traj(auto="bad", skill_meta="skillB"))
    assert sug.label == "bad"
    assert sug.source == "classifier"


def test_metrics_aggregation_across_jsonl_lines(tmp_path: Path) -> None:
    """T3-06 plans to append updates over time; the loader sums
    across lines for the same skill."""
    _write_metrics(
        tmp_path,
        [
            {"skill_name": "agg", "good": 8, "bad": 0},
            {"skill_name": "agg", "good": 15, "bad": 0},
        ],
    )
    fn = build_suggestion_fn(tmp_path)
    sug = fn(_traj(auto="unreviewed", skill_meta="agg"))
    assert sug is not None
    assert sug.label == "good"
    assert sug.source == "metrics"
    # 23 good / 23 decisive = 1.0
    assert sug.confidence == 1.0


# ---------------------------------------------------------------------------
# Direct metrics_override_for unit tests
# ---------------------------------------------------------------------------


def test_metrics_override_for_handles_unknown_skill() -> None:
    assert metrics_override_for("nothere", {}) is None


def test_metrics_override_for_threshold_boundary() -> None:
    """Exactly OVERRIDE_THRESHOLD with MIN_INVOCATIONS_FOR_OVERRIDE
    → override fires."""
    # OVERRIDE_THRESHOLD = 0.95 → at 19 good / 1 bad (20 total),
    # ratio = 0.95 exactly.
    dist = {"good": 19, "bad": 1, "preference_pair": 0}
    sug = metrics_override_for("s", {"s": dist})
    assert sug is not None
    assert sug.label == "good"


# ---------------------------------------------------------------------------
# Skill name extraction
# ---------------------------------------------------------------------------


def test_extract_skill_name_from_metadata() -> None:
    assert extract_skill_name_from(_traj(skill_meta="explicit-skill")) == "explicit-skill"


def test_extract_skill_name_from_tool_calls() -> None:
    assert extract_skill_name_from(_traj(skill_tool="skill_my-skill")) == "my-skill"


def test_extract_skill_name_athena_prefix() -> None:
    assert extract_skill_name_from(_traj(skill_tool="athena_skill_other")) == "other"


def test_extract_skill_name_returns_none_when_absent() -> None:
    assert extract_skill_name_from(_traj()) is None


# ---------------------------------------------------------------------------
# Constants are exposed
# ---------------------------------------------------------------------------


def test_thresholds_exposed() -> None:
    """Docs reference these — guard against accidental removal."""
    assert MIN_INVOCATIONS_FOR_OVERRIDE > 0
    assert 0.5 < OVERRIDE_THRESHOLD <= 1.0
