"""T7-03.2 — run_eval composition tests.

Stub the underlying run_fn so the batch never boots a real
Agent — the scoring layer is what we're testing here.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.eval.runner import parse_cases_file, run_eval
from athena.eval.summary import EvalCase
from athena.headless.result import RunResult


def _stub_run_fn(
    *, task, cfg, workspace, model, run_id, timeout_s,
    status: str = "ok",
    answer: str | None = None,
    error: str | None = None,
):
    """Mimics run_headless. The default returns ``status=ok``
    with an answer derived from the task — tests override via
    factory closures."""
    return RunResult(
        run_id=run_id or "r-stub",
        status=status,  # type: ignore[arg-type]
        started_at="2026-05-21T00:00:00.000000Z",
        finished_at="2026-05-21T00:00:01.000000Z",
        duration_s=0.5,
        task=task, workspace=str(workspace),
        model=model or cfg.model, profile="default",
        session_id="s-stub-1",
        tool_calls=[], tokens={"prompt": 1, "completion": 1,
                               "cache_read": 0, "cache_creation": 0},
        cost_est=0.0,
        assistant_text=(answer if answer is not None else f"answer for: {task}"),
        error=error,
    )


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(model="stub-model", profile="default")


# ---------------------------------------------------------------
# parse_cases_file
# ---------------------------------------------------------------


def test_parse_cases_basic(tmp_path: Path):
    f = tmp_path / "cases.jsonl"
    f.write_text(
        '{"task": "what is 2+2", "expected": "4"}\n'
        '{"task": "name a color", "expected": "red", "scorer": "contains"}\n',
        encoding="utf-8",
    )
    cases = parse_cases_file(f)
    assert len(cases) == 2
    assert cases[0].task == "what is 2+2"
    assert cases[0].expected == "4"
    assert cases[1].scorer == "contains"


def test_parse_cases_skips_blanks_and_comments(tmp_path: Path):
    f = tmp_path / "cases.jsonl"
    f.write_text(
        "# header comment\n"
        "\n"
        '{"task": "T1", "expected": "E1"}\n'
        "  # indented comment\n"
        '{"task": "T2", "expected": "E2"}\n',
        encoding="utf-8",
    )
    cases = parse_cases_file(f)
    assert [c.task for c in cases] == ["T1", "T2"]


def test_parse_cases_line_numbered_errors(tmp_path: Path):
    f = tmp_path / "cases.jsonl"
    f.write_text(
        '{"task": "ok", "expected": "x"}\n'
        'not json\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 2.*not valid JSON"):
        parse_cases_file(f)


def test_parse_cases_missing_expected_line_numbered(tmp_path: Path):
    f = tmp_path / "cases.jsonl"
    f.write_text('{"task": "no expected here"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1.*expected"):
        parse_cases_file(f)


def test_parse_cases_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_cases_file("/no/such/cases.jsonl")


# ---------------------------------------------------------------
# run_eval — happy path: all pass with `exact` scorer
# ---------------------------------------------------------------


def test_run_eval_all_pass_with_exact(tmp_path: Path):
    """Three cases, stub returns the expected answer for each
    — should be 3/3 pass."""
    cases = [
        EvalCase(task="t1", expected="A1", case_id="e-001"),
        EvalCase(task="t2", expected="A2", case_id="e-002"),
        EvalCase(task="t3", expected="A3", case_id="e-003"),
    ]
    # Map task → expected answer so the stub returns the right
    # text per case.
    answers = {"t1": "A1", "t2": "A2", "t3": "A3"}

    def _stub(*, task, **kw):
        return _stub_run_fn(task=task, answer=answers[task], **kw)

    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub,
    )
    assert summary.total == 3
    assert summary.passed == 3
    assert summary.failed == 0
    assert summary.errored == 0
    assert summary.pass_rate == 1.0
    # The summary file landed.
    assert (tmp_path / "out" / "eval-summary.json").exists()
    # scores.jsonl too.
    assert (tmp_path / "out" / "scores.jsonl").exists()


def test_run_eval_mixed_results(tmp_path: Path):
    cases = [
        EvalCase(task="match", expected="hello", case_id="e-pass"),
        EvalCase(task="miss", expected="hello", case_id="e-fail"),
    ]

    def _stub(*, task, **kw):
        if task == "match":
            return _stub_run_fn(task=task, answer="hello", **kw)
        return _stub_run_fn(task=task, answer="bye", **kw)

    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub,
    )
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.errored == 0


# ---------------------------------------------------------------
# Per-case scorer override
# ---------------------------------------------------------------


def test_per_case_scorer_overrides_default(tmp_path: Path):
    """The default is `exact`; this case overrides with
    `contains` which is more permissive."""
    cases = [
        EvalCase(
            task="contains-test",
            expected="answer",
            case_id="e-001",
            scorer="contains",
        ),
    ]
    def _stub(*, task, **kw):
        # "the answer is 42" CONTAINS "answer" but isn't equal.
        return _stub_run_fn(task=task, answer="the answer is 42", **kw)

    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub,
    )
    assert summary.passed == 1
    # And the scores.jsonl records which scorer ran per case.
    score_line = (tmp_path / "out" / "scores.jsonl").read_text().strip()
    row = json.loads(score_line)
    assert row["scorer"] == "contains"


# ---------------------------------------------------------------
# Status handling — run that didn't complete isn't scored
# ---------------------------------------------------------------


def test_errored_runs_counted_separately(tmp_path: Path):
    """A case whose underlying run errored shows up in
    `errored`, NOT `failed`. The scorer isn't even invoked —
    the details says so explicitly."""
    cases = [
        EvalCase(task="will-error", expected="x", case_id="e-err"),
    ]
    def _stub(*, task, **kw):
        return _stub_run_fn(task=task, status="error", error="boom", **kw)

    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub,
    )
    assert summary.passed == 0
    assert summary.failed == 0
    assert summary.errored == 1
    # Score row explains.
    row = json.loads(
        (tmp_path / "out" / "scores.jsonl").read_text().strip()
    )
    assert "run did not complete" in row["details"]
    assert row["scorer"] == "exact"  # scorer name recorded even when not invoked


# ---------------------------------------------------------------
# JSON path scorer end-to-end
# ---------------------------------------------------------------


def test_json_path_scorer_end_to_end(tmp_path: Path):
    cases = [
        EvalCase(
            task="t",
            expected={"path": "data.id", "value": 7},
            scorer="json_path",
            case_id="e-json",
        ),
    ]
    def _stub(*, task, **kw):
        return _stub_run_fn(
            task=task,
            answer='{"data": {"id": 7, "name": "x"}}',
            **kw,
        )

    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub,
    )
    assert summary.passed == 1


# ---------------------------------------------------------------
# by_scorer histogram
# ---------------------------------------------------------------


def test_by_scorer_histogram(tmp_path: Path):
    """Mixed scorers → by_scorer counts each correctly."""
    cases = [
        EvalCase(task="t1", expected="A", case_id="e-1", scorer="exact"),
        EvalCase(task="t2", expected="A", case_id="e-2", scorer="exact"),
        EvalCase(task="t3", expected="answer", case_id="e-3", scorer="contains"),
    ]
    def _stub(*, task, **kw):
        if task == "t1":
            return _stub_run_fn(task=task, answer="A", **kw)        # pass
        if task == "t2":
            return _stub_run_fn(task=task, answer="B", **kw)        # fail
        return _stub_run_fn(task=task, answer="the answer is", **kw)  # contains pass

    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub,
    )
    assert summary.by_scorer["exact"] == {
        "total": 2, "passed": 1, "failed": 1, "errored": 0,
    }
    assert summary.by_scorer["contains"] == {
        "total": 1, "passed": 1, "failed": 0, "errored": 0,
    }


# ---------------------------------------------------------------
# Case ID minting + envelope filename derivation
# ---------------------------------------------------------------


def test_case_ids_minted_when_absent(tmp_path: Path):
    """Cases without case_id get one minted at eval time so
    --baseline can join on a stable key."""
    cases = [
        EvalCase(task="t", expected="x"),  # no case_id
    ]
    def _stub(*, task, **kw):
        return _stub_run_fn(task=task, answer="x", **kw)
    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub,
    )
    assert summary.cases[0].case_id.startswith("e-")
    # And the envelope filename derives from the minted ID.
    case_id = summary.cases[0].case_id
    assert (tmp_path / "out" / f"{case_id}.json").exists()


# ---------------------------------------------------------------
# --baseline DIR diff
# ---------------------------------------------------------------


def test_baseline_regression_detection(tmp_path: Path):
    """Run 1 (baseline): e-1 passes, e-2 fails.
    Run 2 (current): e-1 fails, e-2 passes.
    Expected: regressions=[e-1], improvements=[e-2]."""
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    # Baseline summary fixture written by hand (mimicking a
    # prior eval run that's now on disk).
    (baseline_dir / "eval-summary.json").write_text(json.dumps({
        "eval_id": "v-baseline",
        "cases": [
            {"case_id": "e-1", "passed": True,  "scorer": "exact",
             "score": 1.0, "run_status": "ok",
             "task_excerpt": "", "actual_excerpt": "",
             "details": "", "envelope_path": "", "run_id": "r-x"},
            {"case_id": "e-2", "passed": False, "scorer": "exact",
             "score": 0.0, "run_status": "ok",
             "task_excerpt": "", "actual_excerpt": "",
             "details": "", "envelope_path": "", "run_id": "r-y"},
        ],
    }), encoding="utf-8")

    cases = [
        EvalCase(task="t1", expected="A", case_id="e-1"),  # baseline pass
        EvalCase(task="t2", expected="B", case_id="e-2"),  # baseline fail
    ]
    def _stub(*, task, **kw):
        # Current run: e-1 fails (regression), e-2 passes (improvement).
        if task == "t1":
            return _stub_run_fn(task=task, answer="WRONG", **kw)
        return _stub_run_fn(task=task, answer="B", **kw)

    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        baseline_dir=baseline_dir,
        _run_fn=_stub,
    )
    assert summary.baseline_id == "v-baseline"
    assert summary.regressions == ["e-1"]
    assert summary.improvements == ["e-2"]


def test_baseline_missing_summary_skips_diff(tmp_path: Path):
    """baseline_dir exists but has no eval-summary.json →
    skip the diff (and emit a warning); the summary should
    NOT have baseline_id set."""
    empty_baseline = tmp_path / "empty-baseline"
    empty_baseline.mkdir()
    cases = [EvalCase(task="t", expected="x", case_id="e-1")]
    def _stub(*, task, **kw):
        return _stub_run_fn(task=task, answer="x", **kw)
    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        baseline_dir=empty_baseline,
        _run_fn=_stub,
    )
    assert summary.baseline_id is None
    assert summary.regressions == []
    assert summary.improvements == []


def test_baseline_unmatched_case_ids_ignored(tmp_path: Path):
    """Cases that exist in baseline but not in current run, or
    vice versa, don't generate phantom regressions/improvements."""
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    (baseline_dir / "eval-summary.json").write_text(json.dumps({
        "eval_id": "v-base",
        "cases": [
            {"case_id": "e-old", "passed": True, "scorer": "exact",
             "score": 1.0, "run_status": "ok",
             "task_excerpt": "", "actual_excerpt": "",
             "details": "", "envelope_path": "", "run_id": ""},
        ],
    }), encoding="utf-8")

    cases = [
        EvalCase(task="new", expected="x", case_id="e-new"),
    ]
    def _stub(*, task, **kw):
        return _stub_run_fn(task=task, answer="x", **kw)
    summary = run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        baseline_dir=baseline_dir,
        _run_fn=_stub,
    )
    # Baseline had e-old (which we didn't run); current has
    # e-new (which baseline didn't have). Neither generates a
    # regression/improvement.
    assert summary.regressions == []
    assert summary.improvements == []
    assert summary.baseline_id == "v-base"


# ---------------------------------------------------------------
# Progress callbacks
# ---------------------------------------------------------------


def test_score_progress_fires_per_case(tmp_path: Path):
    cases = [
        EvalCase(task=f"t{i}", expected="x", case_id=f"e-{i:03d}")
        for i in range(4)
    ]
    def _stub(*, task, **kw):
        return _stub_run_fn(task=task, answer="x", **kw)

    log: list[tuple[bool, int, int]] = []
    run_eval(
        cases, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        score_progress=lambda es, done, total: log.append((es.passed, done, total)),
        _run_fn=_stub,
    )
    assert log == [(True, 1, 4), (True, 2, 4), (True, 3, 4), (True, 4, 4)]


# ---------------------------------------------------------------
# Empty cases list
# ---------------------------------------------------------------


def test_empty_cases_produces_empty_summary(tmp_path: Path):
    summary = run_eval(
        [], cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", default_scorer="exact",
        _run_fn=_stub_run_fn,
    )
    assert summary.total == 0
    assert summary.passed == 0
    assert summary.pass_rate == 0.0
    assert summary.avg_score == 0.0
    # Files still written.
    assert (tmp_path / "out" / "eval-summary.json").exists()


# ---------------------------------------------------------------
# Default scorer validation up front
# ---------------------------------------------------------------


def test_unknown_default_scorer_rejected(tmp_path: Path):
    """A typo'd --scorer NAME should fail BEFORE any batch
    work fires."""
    cases = [EvalCase(task="t", expected="x")]
    with pytest.raises(KeyError, match="unknown scorer"):
        run_eval(
            cases, cfg=_cfg(), workspace_default=tmp_path,
            output_dir=tmp_path / "out",
            default_scorer="nonexistent",
            _run_fn=_stub_run_fn,
        )
