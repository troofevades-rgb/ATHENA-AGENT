"""Benchmark runner — discovery + compare logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Add scripts/bench to importable paths so the runner module loads.
_SCRIPTS = Path(__file__).parent.parent.parent / "scripts"
import sys

sys.path.insert(0, str(_SCRIPTS.parent))


from scripts.bench import runner

# ---- discovery ----------------------------------------------------


def test_discover_benches_finds_run_modules() -> None:
    benches = runner.discover_benches()
    names = [name for name, _fn in benches]
    assert "tool_call_latency" in names
    assert "skill_discovery" in names
    # __init__ and runner itself never appear.
    assert "__init__" not in names
    assert "runner" not in names


def test_discover_benches_returns_sorted() -> None:
    names = [name for name, _ in runner.discover_benches()]
    assert names == sorted(names)


# ---- compare_to_baseline -------------------------------------------


def _result(name: str, value: float, status: str = "ok") -> dict:
    return {
        "name": name,
        "metric": "p50_ms",
        "value": value,
        "status": status,
    }


def test_compare_flags_regression_over_threshold() -> None:
    current = {"results": [_result("a", 12.0)]}
    baseline = {"results": [_result("a", 10.0)]}
    report = runner.compare_to_baseline(current, baseline, threshold=0.1)
    assert len(report["regressions"]) == 1
    assert report["regressions"][0]["delta_pct"] == pytest.approx(0.2)


def test_compare_no_regression_under_threshold() -> None:
    """5% slower with a 10% threshold → not a regression."""
    current = {"results": [_result("a", 10.5)]}
    baseline = {"results": [_result("a", 10.0)]}
    report = runner.compare_to_baseline(current, baseline, threshold=0.1)
    assert report["regressions"] == []
    assert report["improvements"] == []


def test_compare_flags_improvement_below_negative_threshold() -> None:
    current = {"results": [_result("a", 7.5)]}
    baseline = {"results": [_result("a", 10.0)]}
    report = runner.compare_to_baseline(current, baseline, threshold=0.1)
    assert len(report["improvements"]) == 1
    assert report["improvements"][0]["delta_pct"] == pytest.approx(-0.25)


def test_compare_handles_missing_baseline_entry() -> None:
    """A bench exists in current but not in baseline — surfaces in
    'missing' rather than crashing or registering as a regression."""
    current = {"results": [_result("new-bench", 5.0)]}
    baseline = {"results": []}
    report = runner.compare_to_baseline(current, baseline)
    assert report["missing"] == ["new-bench"]
    assert report["regressions"] == []


def test_compare_skips_errored_results() -> None:
    """A bench that errored in current shouldn't compare against
    anything — it'll get flagged on the dashboard separately."""
    current = {"results": [_result("a", 0.0, status="error")]}
    baseline = {"results": [_result("a", 10.0)]}
    report = runner.compare_to_baseline(current, baseline)
    assert report["regressions"] == []


def test_compare_zero_baseline_skipped() -> None:
    """Avoid div-by-zero on a degenerate baseline."""
    current = {"results": [_result("a", 5.0)]}
    baseline = {"results": [_result("a", 0.0)]}
    report = runner.compare_to_baseline(current, baseline)
    assert report["regressions"] == []
    assert report["improvements"] == []


def test_compare_skips_errored_baseline() -> None:
    current = {"results": [_result("a", 5.0)]}
    baseline = {"results": [_result("a", 10.0, status="error")]}
    report = runner.compare_to_baseline(current, baseline)
    # Treated as missing since the baseline entry isn't usable.
    assert "a" in report["missing"]


# ---- render_comparison --------------------------------------------


def test_render_no_regressions() -> None:
    report = {
        "threshold": 0.1,
        "regressions": [],
        "improvements": [],
        "missing": [],
    }
    out = runner.render_comparison(report)
    assert "no regressions" in out


def test_render_regression_includes_delta() -> None:
    report = {
        "threshold": 0.1,
        "regressions": [
            {
                "name": "tool_call_latency",
                "metric": "p50_ms",
                "baseline": 10.0,
                "current": 13.0,
                "delta_pct": 0.3,
            }
        ],
        "improvements": [],
        "missing": [],
    }
    out = runner.render_comparison(report)
    assert "tool_call_latency" in out
    assert "+30.0%" in out
    assert "10.000" in out and "13.000" in out


def test_render_improvement_included() -> None:
    report = {
        "threshold": 0.1,
        "regressions": [],
        "improvements": [
            {
                "name": "x",
                "metric": "ms",
                "baseline": 10,
                "current": 7,
                "delta_pct": -0.3,
            }
        ],
        "missing": [],
    }
    out = runner.render_comparison(report)
    assert "improvement" in out
    assert "-30.0%" in out


def test_render_missing_listed() -> None:
    report = {
        "threshold": 0.1,
        "regressions": [],
        "improvements": [],
        "missing": ["new_bench"],
    }
    out = runner.render_comparison(report)
    assert "new_bench" in out
    assert "not in baseline" in out


# ---- write_results / write_baseline --------------------------------


def test_write_results_creates_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_RESULTS_DIR", tmp_path / "results")
    suite = {"results": [_result("a", 1.0)]}
    output = runner.write_results(suite)
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["results"][0]["name"] == "a"


def test_write_baseline_creates_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"
    runner.write_baseline({"results": [_result("a", 1.0)]}, target=target)
    assert target.exists()


# ---- the actual benches run end-to-end ------------------------------


def test_tool_call_latency_bench_runs() -> None:
    """Sanity: the bench itself doesn't raise + produces the
    expected shape."""
    from scripts.bench import tool_call_latency

    result = tool_call_latency.run()
    assert result["name"] == "tool_call_latency"
    assert result["metric"] == "p50_ms"
    assert result["value"] > 0
    assert result["samples"] == 100


def test_skill_discovery_bench_runs() -> None:
    from scripts.bench import skill_discovery

    result = skill_discovery.run()
    assert result["name"] == "skill_discovery"
    assert result["metric"] == "mean_ms"
    assert result["value"] > 0
    assert result["skill_count"] == 100


def test_full_suite_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: discover + run + write. Each bench appears in the
    result with status=ok."""
    monkeypatch.setattr(runner, "_RESULTS_DIR", tmp_path)
    suite = runner.run_suite()
    names = {r["name"] for r in suite["results"]}
    assert "tool_call_latency" in names
    assert "skill_discovery" in names
    for r in suite["results"]:
        assert r["status"] == "ok"
    assert suite["duration_ms"] > 0
