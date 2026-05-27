"""Per-task results, aggregate report, JSON serialization, compare()."""

from __future__ import annotations

import dataclasses
import json
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

# Status taxonomy:
#   passed  — verify_fn returned True
#   failed  — verify_fn returned False (or raised, treated as False
#             with the exception recorded)
#   timeout — task exceeded its timeout_s budget
#   error   — runner-side failure (agent crashed, setup_fn raised,
#             mock MCP server failed to start). Counted SEPARATELY
#             from failed so diagnosis isn't conflated.
Status = Literal["passed", "failed", "timeout", "error"]


@dataclasses.dataclass
class TaskResult:
    """Outcome of running one task."""

    task_id: str
    bucket: str
    status: Status
    duration_s: float
    turns: int = 0
    tool_calls: int = 0
    eval_tokens: int = 0
    error: str = ""
    # Excerpted assistant text for diagnosis. NOT used for verification —
    # this is just a breadcrumb for "why did this fail?" inspection.
    final_assistant_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "bucket": self.bucket,
            "status": self.status,
            "duration_s": round(self.duration_s, 3),
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "eval_tokens": self.eval_tokens,
            "error": self.error,
            "final_assistant_excerpt": self.final_assistant_excerpt,
        }

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclasses.dataclass
class EvalReport:
    """Aggregate report over a run of N tasks.

    Single headline number: ``pass_rate``. Everything else is for
    diagnosis.
    """

    model: str
    policy: str
    task_set: str
    started_at: float
    finished_at: float
    results: list[TaskResult]

    # ----- aggregate numbers ----------------------------------------

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def timed_out(self) -> int:
        return sum(1 for r in self.results if r.status == "timeout")

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.status == "error")

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def duration_s(self) -> float:
        return self.finished_at - self.started_at

    def by_bucket(self) -> dict[str, dict[str, Any]]:
        """Per-bucket stats: count, passed, pass_rate."""
        buckets: dict[str, list[TaskResult]] = {}
        for r in self.results:
            buckets.setdefault(r.bucket, []).append(r)
        out: dict[str, dict[str, Any]] = {}
        for name, group in buckets.items():
            passed = sum(1 for r in group if r.status == "passed")
            out[name] = {
                "total": len(group),
                "passed": passed,
                "pass_rate": passed / len(group) if group else 0.0,
            }
        return out

    def mean_turns(self) -> float:
        """Mean turns across all tasks (passed or not)."""
        if not self.results:
            return 0.0
        return sum(r.turns for r in self.results) / len(self.results)

    def mean_tool_calls(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.tool_calls for r in self.results) / len(self.results)

    def mean_eval_tokens(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.eval_tokens for r in self.results) / len(self.results)

    # ----- serialization --------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "policy": self.policy,
            "task_set": self.task_set,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(self.duration_s, 3),
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "errored": self.errored,
            "pass_rate": round(self.pass_rate, 4),
            "by_bucket": {
                name: {
                    **stats,
                    "pass_rate": round(stats["pass_rate"], 4),
                }
                for name, stats in self.by_bucket().items()
            },
            "mean_turns": round(self.mean_turns(), 2),
            "mean_tool_calls": round(self.mean_tool_calls(), 2),
            "mean_eval_tokens": round(self.mean_eval_tokens(), 1),
            "results": [r.to_dict() for r in self.results],
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalReport:
        """Reverse of ``to_dict`` for ``compare`` to load saved reports."""
        results = [
            TaskResult(
                task_id=r["task_id"],
                bucket=r.get("bucket", "general"),
                status=r.get("status", "error"),
                duration_s=float(r.get("duration_s", 0.0)),
                turns=int(r.get("turns", 0)),
                tool_calls=int(r.get("tool_calls", 0)),
                eval_tokens=int(r.get("eval_tokens", 0)),
                error=r.get("error", ""),
                final_assistant_excerpt=r.get("final_assistant_excerpt", ""),
            )
            for r in data.get("results", [])
        ]
        return cls(
            model=data.get("model", ""),
            policy=data.get("policy", ""),
            task_set=data.get("task_set", ""),
            started_at=float(data.get("started_at", 0.0)),
            finished_at=float(data.get("finished_at", 0.0)),
            results=results,
        )


# ---------------------------------------------------------------------------
# Compare two reports
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CompareResult:
    """Pairwise diff between two reports.

    - **regressions**: task_ids that PASSED in baseline and FAILED in
      current. The set you care about for "did training help?"
    - **improvements**: task_ids that FAILED in baseline and PASS now.
    - **unchanged_pass / unchanged_fail**: task_ids stable across runs.
    - **only_in_baseline / only_in_current**: tasks present in one
      report but not the other (e.g. task set changed between runs).
    """

    baseline_model: str
    current_model: str
    baseline_pass_rate: float
    current_pass_rate: float
    delta_pass_rate: float
    regressions: list[str]
    improvements: list[str]
    unchanged_pass: list[str]
    unchanged_fail: list[str]
    only_in_baseline: list[str]
    only_in_current: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_model": self.baseline_model,
            "current_model": self.current_model,
            "baseline_pass_rate": round(self.baseline_pass_rate, 4),
            "current_pass_rate": round(self.current_pass_rate, 4),
            "delta_pass_rate": round(self.delta_pass_rate, 4),
            "regressions_count": len(self.regressions),
            "improvements_count": len(self.improvements),
            "unchanged_pass_count": len(self.unchanged_pass),
            "unchanged_fail_count": len(self.unchanged_fail),
            "regressions": self.regressions,
            "improvements": self.improvements,
            "unchanged_pass": self.unchanged_pass,
            "unchanged_fail": self.unchanged_fail,
            "only_in_baseline": self.only_in_baseline,
            "only_in_current": self.only_in_current,
        }


def compare_reports(
    baseline: EvalReport, current: EvalReport
) -> CompareResult:
    """Diff two reports by ``task_id``. Tasks not present in both are
    surfaced separately rather than dropped silently."""
    base_by_id = {r.task_id: r for r in baseline.results}
    cur_by_id = {r.task_id: r for r in current.results}

    common = set(base_by_id) & set(cur_by_id)
    only_baseline = sorted(set(base_by_id) - set(cur_by_id))
    only_current = sorted(set(cur_by_id) - set(base_by_id))

    regressions, improvements = [], []
    unchanged_pass, unchanged_fail = [], []
    for tid in sorted(common):
        b_pass = base_by_id[tid].passed
        c_pass = cur_by_id[tid].passed
        if b_pass and not c_pass:
            regressions.append(tid)
        elif (not b_pass) and c_pass:
            improvements.append(tid)
        elif b_pass and c_pass:
            unchanged_pass.append(tid)
        else:
            unchanged_fail.append(tid)

    return CompareResult(
        baseline_model=baseline.model,
        current_model=current.model,
        baseline_pass_rate=baseline.pass_rate,
        current_pass_rate=current.pass_rate,
        delta_pass_rate=current.pass_rate - baseline.pass_rate,
        regressions=regressions,
        improvements=improvements,
        unchanged_pass=unchanged_pass,
        unchanged_fail=unchanged_fail,
        only_in_baseline=only_baseline,
        only_in_current=only_current,
    )


__all__ = [
    "Status",
    "TaskResult",
    "EvalReport",
    "CompareResult",
    "compare_reports",
]
