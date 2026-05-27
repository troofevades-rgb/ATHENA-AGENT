"""Report aggregation + JSON round-trip + compare()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.eval.agent.report import (
    CompareResult,
    EvalReport,
    TaskResult,
    compare_reports,
)


def _make_report(
    *,
    model: str = "m",
    task_outcomes: dict[str, str] | None = None,
    buckets: dict[str, str] | None = None,
) -> EvalReport:
    """Build a synthetic report. ``task_outcomes`` maps task_id ->
    status; ``buckets`` maps task_id -> bucket name."""
    outcomes = task_outcomes or {}
    buckets = buckets or {}
    results = [
        TaskResult(
            task_id=tid,
            bucket=buckets.get(tid, "general"),
            status=status,  # type: ignore[arg-type]
            duration_s=1.0,
            turns=2,
            tool_calls=3,
            eval_tokens=100,
        )
        for tid, status in outcomes.items()
    ]
    return EvalReport(
        model=model,
        policy="heuristic",
        task_set="default",
        started_at=1000.0,
        finished_at=1100.0,
        results=results,
    )


# ---------------------------------------------------------------------------
# Headline numbers
# ---------------------------------------------------------------------------


def test_pass_rate_is_passed_over_total():
    r = _make_report(task_outcomes={"a": "passed", "b": "failed", "c": "passed"})
    assert r.pass_rate == pytest.approx(2 / 3)


def test_pass_rate_zero_division_safe():
    r = _make_report(task_outcomes={})
    assert r.pass_rate == 0.0


def test_status_counts_separate_failed_timeout_error():
    r = _make_report(
        task_outcomes={
            "a": "passed",
            "b": "failed",
            "c": "timeout",
            "d": "error",
        }
    )
    assert r.passed == 1
    assert r.failed == 1
    assert r.timed_out == 1
    assert r.errored == 1


def test_means_over_results():
    r = _make_report(task_outcomes={"a": "passed", "b": "failed"})
    # Each synthetic result has turns=2, tool_calls=3, eval_tokens=100.
    assert r.mean_turns() == 2.0
    assert r.mean_tool_calls() == 3.0
    assert r.mean_eval_tokens() == 100.0


# ---------------------------------------------------------------------------
# By-bucket aggregation
# ---------------------------------------------------------------------------


def test_by_bucket_groups_results():
    r = _make_report(
        task_outcomes={
            "f1": "passed",
            "f2": "failed",
            "s1": "passed",
        },
        buckets={"f1": "file_ops", "f2": "file_ops", "s1": "shell"},
    )
    by = r.by_bucket()
    assert by["file_ops"]["total"] == 2
    assert by["file_ops"]["passed"] == 1
    assert by["file_ops"]["pass_rate"] == 0.5
    assert by["shell"]["total"] == 1
    assert by["shell"]["passed"] == 1
    assert by["shell"]["pass_rate"] == 1.0


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


def test_to_dict_contains_headline_fields():
    r = _make_report(task_outcomes={"a": "passed", "b": "failed"})
    d = r.to_dict()
    for key in (
        "model", "policy", "task_set", "started_at", "finished_at",
        "total", "passed", "failed", "timed_out", "errored",
        "pass_rate", "by_bucket", "mean_turns", "mean_tool_calls",
        "mean_eval_tokens", "results",
    ):
        assert key in d, f"missing key: {key}"


def test_write_json_round_trips(tmp_path: Path):
    r = _make_report(
        task_outcomes={"a": "passed", "b": "failed", "c": "timeout"},
        buckets={"a": "file_ops", "b": "file_ops", "c": "shell"},
    )
    out = tmp_path / "report.json"
    r.write_json(out)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    restored = EvalReport.from_dict(data)
    assert restored.total == 3
    assert restored.pass_rate == pytest.approx(1 / 3)
    assert restored.by_bucket()["file_ops"]["total"] == 2


def test_write_json_atomic(tmp_path: Path):
    """Tmp + rename, never leave a half-written file."""
    r = _make_report(task_outcomes={"a": "passed"})
    out = tmp_path / "report.json"
    r.write_json(out)
    # No .tmp leftover.
    assert not (tmp_path / "report.json.tmp").exists()


# ---------------------------------------------------------------------------
# Compare two reports
# ---------------------------------------------------------------------------


def test_compare_identifies_regressions():
    base = _make_report(
        model="base", task_outcomes={"a": "passed", "b": "passed"}
    )
    new = _make_report(
        model="lora", task_outcomes={"a": "passed", "b": "failed"}
    )
    diff = compare_reports(base, new)
    assert diff.regressions == ["b"]
    assert diff.improvements == []


def test_compare_identifies_improvements():
    base = _make_report(
        model="base", task_outcomes={"a": "failed", "b": "passed"}
    )
    new = _make_report(
        model="lora", task_outcomes={"a": "passed", "b": "passed"}
    )
    diff = compare_reports(base, new)
    assert diff.improvements == ["a"]
    assert diff.regressions == []


def test_compare_separates_unchanged_groups():
    base = _make_report(
        task_outcomes={"a": "passed", "b": "failed", "c": "passed"}
    )
    new = _make_report(
        task_outcomes={"a": "passed", "b": "failed", "c": "passed"}
    )
    diff = compare_reports(base, new)
    assert diff.unchanged_pass == ["a", "c"]
    assert diff.unchanged_fail == ["b"]


def test_compare_surfaces_task_set_drift():
    """A task that exists in one report but not the other should
    NOT be silently dropped — surfaces in only_in_*."""
    base = _make_report(task_outcomes={"a": "passed", "b": "passed"})
    new = _make_report(task_outcomes={"a": "passed", "c": "passed"})
    diff = compare_reports(base, new)
    assert diff.only_in_baseline == ["b"]
    assert diff.only_in_current == ["c"]
    # Common task "a" is unchanged.
    assert diff.unchanged_pass == ["a"]


def test_compare_delta_pass_rate():
    base = _make_report(
        task_outcomes={"a": "passed", "b": "failed", "c": "failed"}
    )
    new = _make_report(
        task_outcomes={"a": "passed", "b": "passed", "c": "failed"}
    )
    diff = compare_reports(base, new)
    assert diff.baseline_pass_rate == pytest.approx(1 / 3)
    assert diff.current_pass_rate == pytest.approx(2 / 3)
    assert diff.delta_pass_rate == pytest.approx(1 / 3)
