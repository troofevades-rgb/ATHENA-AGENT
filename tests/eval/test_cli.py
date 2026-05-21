"""T7-03.3 — `athena eval` CLI integration tests.

Patches run_headless so the suite never boots a real Agent.
Tests the full CLI plumbing: argparse, output-dir resolution,
exit codes, baseline diff, --json envelope, validation paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.headless.result import RunResult


def _build_run_result(
    *, task: str, run_id: str, workspace: Any,
    answer: str = "answer", status: str = "ok",
    error: str | None = None,
):
    return RunResult(
        run_id=run_id,
        status=status,  # type: ignore[arg-type]
        started_at="2026-05-21T00:00:00.000000Z",
        finished_at="2026-05-21T00:00:01.000000Z",
        duration_s=0.1,
        task=task, workspace=str(workspace),
        model="stub-model", profile="default",
        session_id="s-stub-1",
        tool_calls=[], tokens={"prompt": 0, "completion": 0,
                               "cache_read": 0, "cache_creation": 0},
        cost_est=0.0, assistant_text=answer, error=error,
    )


@pytest.fixture
def stub_eval_env(monkeypatch, tmp_path: Path):
    """Patch run_headless (the package re-export AND the
    module-level function — batch_run imports from the
    package) + redirect profile_dir → tmp_path."""
    import athena.cli.eval as eval_cli
    import athena.headless as headless_pkg
    import athena.headless.runner as runner_mod

    answers = {"default": "answer"}

    def _stub(task, *, cfg, workspace, model=None, run_id=None,
              timeout_s=None, on_info=None, agent=None,
              _agent_factory=None):
        # The test's `answers` dict drives the per-task answer.
        a = answers.get(task, answers.get("default", "answer"))
        if isinstance(a, dict):
            return _build_run_result(
                task=task, run_id=run_id or "r-auto",
                workspace=workspace, **a,
            )
        return _build_run_result(
            task=task, run_id=run_id or "r-auto",
            workspace=workspace, answer=str(a),
        )

    monkeypatch.setattr(runner_mod, "run_headless", _stub)
    monkeypatch.setattr(headless_pkg, "run_headless", _stub)
    monkeypatch.setattr(eval_cli, "profile_dir",
                        lambda profile="default": tmp_path)

    return SimpleNamespace(answers=answers, tmp_path=tmp_path)


def _run_eval_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    """Call the eval CLI's main(argv) directly. Capture
    stdout + stderr."""
    from athena.cli.eval import main
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _write_cases(tmp_path: Path, cases: list[dict]) -> Path:
    f = tmp_path / "cases.jsonl"
    f.write_text(
        "\n".join(json.dumps(c) for c in cases) + "\n",
        encoding="utf-8",
    )
    return f


# ---------------------------------------------------------------
# Validation
# ---------------------------------------------------------------


def test_missing_cases_file_exits_2(stub_eval_env, capsys, tmp_path: Path):
    code, _out, err = _run_eval_cli([str(tmp_path / "nope.jsonl")], capsys)
    assert code == 2
    assert "not found" in err


def test_unknown_default_scorer_exits_2(stub_eval_env, capsys, tmp_path: Path):
    f = _write_cases(tmp_path, [{"task": "t", "expected": "x"}])
    code, _out, err = _run_eval_cli(
        [str(f), "--scorer", "nonexistent", "-C", str(tmp_path), "--quiet"],
        capsys,
    )
    assert code == 2
    assert "unknown scorer" in err
    assert "available scorers" in err


def test_bad_json_in_cases_exits_2(stub_eval_env, capsys, tmp_path: Path):
    f = tmp_path / "cases.jsonl"
    f.write_text("not json\n", encoding="utf-8")
    code, _out, err = _run_eval_cli([str(f)], capsys)
    assert code == 2
    assert "not valid JSON" in err


def test_empty_cases_file_exits_0(stub_eval_env, capsys, tmp_path: Path):
    f = tmp_path / "cases.jsonl"
    f.write_text("", encoding="utf-8")
    code, _out, err = _run_eval_cli(
        [str(f), "-C", str(tmp_path), "--quiet"], capsys,
    )
    assert code == 0
    assert "no entries" in err


# ---------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------


def test_all_pass_exits_0(stub_eval_env, capsys, tmp_path: Path):
    stub_eval_env.answers["t1"] = "A"
    stub_eval_env.answers["t2"] = "B"
    f = _write_cases(tmp_path, [
        {"task": "t1", "expected": "A", "case_id": "e-001"},
        {"task": "t2", "expected": "B", "case_id": "e-002"},
    ])
    code, _out, err = _run_eval_cli(
        [str(f), "-o", str(tmp_path / "out"),
         "-C", str(tmp_path), "--quiet"],
        capsys,
    )
    assert code == 0
    assert "2/2 passed" in err
    summary = json.loads(
        (tmp_path / "out" / "eval-summary.json").read_text()
    )
    assert summary["passed"] == 2
    assert summary["pass_rate"] == 1.0


def test_any_failure_exits_1(stub_eval_env, capsys, tmp_path: Path):
    stub_eval_env.answers["match"] = "ok"
    stub_eval_env.answers["miss"]  = "wrong"
    f = _write_cases(tmp_path, [
        {"task": "match", "expected": "ok",  "case_id": "e-1"},
        {"task": "miss",  "expected": "ok",  "case_id": "e-2"},
    ])
    code, _out, err = _run_eval_cli(
        [str(f), "-o", str(tmp_path / "out"),
         "-C", str(tmp_path), "--quiet"],
        capsys,
    )
    assert code == 1
    assert "1/2 passed" in err


def test_error_status_counted_as_errored_and_exits_1(
    stub_eval_env, capsys, tmp_path: Path,
):
    stub_eval_env.answers["t"] = {"status": "error", "error": "boom"}
    f = _write_cases(tmp_path, [
        {"task": "t", "expected": "x", "case_id": "e-1"},
    ])
    code, _out, err = _run_eval_cli(
        [str(f), "-o", str(tmp_path / "out"),
         "-C", str(tmp_path), "--quiet"],
        capsys,
    )
    assert code == 1
    summary = json.loads(
        (tmp_path / "out" / "eval-summary.json").read_text()
    )
    assert summary["errored"] == 1
    assert summary["failed"] == 0
    # In the summary stderr line.
    assert "1 errored" in err


# ---------------------------------------------------------------
# --json envelope on stdout
# ---------------------------------------------------------------


def test_json_mode_single_line_on_stdout(
    stub_eval_env, capsys, tmp_path: Path,
):
    stub_eval_env.answers["t"] = "x"
    f = _write_cases(tmp_path, [
        {"task": "t", "expected": "x", "case_id": "e-1"},
    ])
    code, out, _err = _run_eval_cli(
        [str(f), "-o", str(tmp_path / "out"),
         "-C", str(tmp_path), "--quiet", "--json"],
        capsys,
    )
    assert code == 0
    body = out.rstrip("\n")
    assert "\n" not in body
    payload = json.loads(body)
    assert payload["passed"] == 1
    assert payload["eval_id"].startswith("v-")


# ---------------------------------------------------------------
# Default output-dir under <profile>/eval/<eval_id>/
# ---------------------------------------------------------------


def test_default_output_dir_under_profile_eval(
    stub_eval_env, capsys, tmp_path: Path,
):
    stub_eval_env.answers["t"] = "x"
    f = _write_cases(tmp_path, [{"task": "t", "expected": "x", "case_id": "e-1"}])
    code, _out, _err = _run_eval_cli(
        [str(f), "-C", str(tmp_path), "--quiet"], capsys,
    )
    assert code == 0
    # <profile_dir>/eval/<eval_id>/eval-summary.json
    evals = list((tmp_path / "eval").iterdir())
    assert len(evals) == 1
    assert (evals[0] / "eval-summary.json").exists()


# ---------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------


def test_baseline_diff_via_cli(stub_eval_env, capsys, tmp_path: Path):
    """Set up a baseline dir with a prior eval-summary; run a
    current eval that flips one case from passing to failing
    + one from failing to passing. Verify the CLI surfaces
    both regressions + improvements."""
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    (baseline_dir / "eval-summary.json").write_text(json.dumps({
        "eval_id": "v-baseline",
        "cases": [
            {"case_id": "e-1", "passed": True,
             "scorer": "exact", "score": 1.0,
             "run_status": "ok",
             "task_excerpt": "", "actual_excerpt": "",
             "details": "", "envelope_path": "", "run_id": ""},
            {"case_id": "e-2", "passed": False,
             "scorer": "exact", "score": 0.0,
             "run_status": "ok",
             "task_excerpt": "", "actual_excerpt": "",
             "details": "", "envelope_path": "", "run_id": ""},
        ],
    }), encoding="utf-8")

    # Current run flips both.
    stub_eval_env.answers["t1"] = "WRONG"  # regression
    stub_eval_env.answers["t2"] = "B"      # improvement
    f = _write_cases(tmp_path, [
        {"task": "t1", "expected": "A", "case_id": "e-1"},
        {"task": "t2", "expected": "B", "case_id": "e-2"},
    ])

    code, _out, err = _run_eval_cli(
        [
            str(f), "-o", str(tmp_path / "out"),
            "--baseline", str(baseline_dir),
            "-C", str(tmp_path), "--quiet",
        ],
        capsys,
    )
    # One passed, one failed → exit 1.
    assert code == 1
    # Stderr reports the diff explicitly.
    assert "1 regression" in err
    assert "1 improvement" in err
    assert "e-1" in err
    assert "e-2" in err


def test_baseline_with_no_summary_file_still_runs(
    stub_eval_env, capsys, tmp_path: Path,
):
    """baseline_dir exists but has no eval-summary.json → eval
    runs anyway; warning logged but no baseline_id set."""
    empty = tmp_path / "no-summary"
    empty.mkdir()
    stub_eval_env.answers["t"] = "x"
    f = _write_cases(tmp_path, [{"task": "t", "expected": "x", "case_id": "e-1"}])
    code, _out, _err = _run_eval_cli(
        [
            str(f), "-o", str(tmp_path / "out"),
            "--baseline", str(empty),
            "-C", str(tmp_path), "--quiet",
        ],
        capsys,
    )
    assert code == 0
    summary = json.loads(
        (tmp_path / "out" / "eval-summary.json").read_text()
    )
    assert "baseline_id" not in summary


# ---------------------------------------------------------------
# Progress lines on stderr
# ---------------------------------------------------------------


def test_progress_lines_emitted_by_default(
    stub_eval_env, capsys, tmp_path: Path,
):
    stub_eval_env.answers["t1"] = "x"
    stub_eval_env.answers["t2"] = "y"
    f = _write_cases(tmp_path, [
        {"task": "t1", "expected": "x", "case_id": "e-1"},
        {"task": "t2", "expected": "x", "case_id": "e-2"},  # will fail
    ])
    code, _out, err = _run_eval_cli(
        [str(f), "-o", str(tmp_path / "out"), "-C", str(tmp_path)],
        capsys,
    )
    assert code == 1
    # Per-case progress + final summary in stderr.
    assert "[   1/2]" in err
    assert "[   2/2]" in err
    assert "PASS" in err
    assert "FAIL" in err
    # Final summary line.
    assert "1/2 passed" in err


def test_quiet_suppresses_progress(
    stub_eval_env, capsys, tmp_path: Path,
):
    stub_eval_env.answers["t"] = "x"
    f = _write_cases(tmp_path, [{"task": "t", "expected": "x", "case_id": "e-1"}])
    code, _out, err = _run_eval_cli(
        [str(f), "-o", str(tmp_path / "out"),
         "-C", str(tmp_path), "--quiet"],
        capsys,
    )
    assert code == 0
    assert "[   1/" not in err
    # Summary line still shows up in non-JSON mode.
    assert "1/1 passed" in err


# ---------------------------------------------------------------
# Per-case scorer override end-to-end
# ---------------------------------------------------------------


def test_per_case_scorer_override_through_cli(
    stub_eval_env, capsys, tmp_path: Path,
):
    """One case uses `contains`, another the default `exact`.
    Stub answers: first contains expected, second doesn't equal
    expected — both should pass through their respective scorers."""
    stub_eval_env.answers["c1"] = "the answer is 42"
    stub_eval_env.answers["c2"] = "42"
    f = _write_cases(tmp_path, [
        {"task": "c1", "expected": "42", "case_id": "e-1",
         "scorer": "contains"},
        {"task": "c2", "expected": "42", "case_id": "e-2"},  # default exact
    ])
    code, _out, err = _run_eval_cli(
        [str(f), "-o", str(tmp_path / "out"),
         "-C", str(tmp_path), "--quiet"],
        capsys,
    )
    assert code == 0
    summary = json.loads(
        (tmp_path / "out" / "eval-summary.json").read_text()
    )
    # Both passed, via different scorers.
    assert summary["passed"] == 2
    assert summary["by_scorer"]["contains"]["passed"] == 1
    assert summary["by_scorer"]["exact"]["passed"] == 1
