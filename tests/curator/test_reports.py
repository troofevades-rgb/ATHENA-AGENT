"""Tests for athena.curator.reports.write_run."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from athena.agent.fork import ForkResult
from athena.curator.reports import write_run


def _parsed(*runs: dict) -> dict:
    return {"runs": list(runs)}


def _fork(**over) -> ForkResult:
    base = dict(
        final_response="ok",
        duration_s=1.2,
        child_session_id="child-abc",
        stdout="some output",
        stderr="",
    )
    base.update(over)
    return ForkResult(**base)


def test_writes_run_json(tmp_path: Path) -> None:
    parsed = _parsed(
        {"skill": "foo", "decision": "KEEP_AS_IS", "target": None, "rationale": "r"},
        {"skill": "bar", "decision": "PRUNE", "target": None, "rationale": "r2"},
    )
    summary = write_run(SimpleNamespace(), _fork(), parsed, logs_root=tmp_path)
    runs = list((tmp_path / "curator").iterdir())
    assert len(runs) == 1
    rj = runs[0] / "run.json"
    assert rj.exists()
    data = json.loads(rj.read_text(encoding="utf-8"))
    assert data["total_skills"] == 2
    assert data["decision_counts"] == {"KEEP_AS_IS": 1, "PRUNE": 1}
    assert data["fork"]["duration_s"] == 1.2
    assert summary["report_path"].endswith("REPORT.md")


def test_writes_report_md(tmp_path: Path) -> None:
    parsed = _parsed(
        {"skill": "foo", "decision": "KEEP_AS_IS", "target": None, "rationale": "fine"},
    )
    write_run(SimpleNamespace(), _fork(), parsed, logs_root=tmp_path)
    runs = list((tmp_path / "curator").iterdir())
    report = (runs[0] / "REPORT.md").read_text(encoding="utf-8")
    assert "# Curator run" in report
    assert "Total skills reviewed: 1" in report
    assert "foo" in report and "KEEP_AS_IS" in report


def test_human_readable_report_lists_each_decision(tmp_path: Path) -> None:
    parsed = _parsed(
        {
            "skill": "a",
            "decision": "CONSOLIDATE_INTO",
            "target": "umbrella-x",
            "rationale": "merge",
        },
        {
            "skill": "b",
            "decision": "CONSOLIDATE_INTO",
            "target": "umbrella-x",
            "rationale": "merge",
        },
        {"skill": "c", "decision": "CREATE_UMBRELLA", "target": "new-cat", "rationale": "spin"},
        {"skill": "d", "decision": "KEEP_AS_IS", "target": None, "rationale": "ok"},
        {"skill": "e", "decision": "PRUNE", "target": None, "rationale": "obsolete"},
    )
    write_run(SimpleNamespace(), _fork(), parsed, logs_root=tmp_path)
    runs = list((tmp_path / "curator").iterdir())
    report = (runs[0] / "REPORT.md").read_text(encoding="utf-8")
    # All five skills must be named, with their decisions and targets.
    for slug in ("a", "b", "c", "d", "e"):
        assert f"**{slug}**" in report
    assert "umbrella-x" in report
    assert "new-cat" in report


def test_dry_run_flag_appears_in_header(tmp_path: Path) -> None:
    write_run(
        SimpleNamespace(),
        _fork(),
        _parsed({"skill": "x", "decision": "KEEP_AS_IS", "target": None, "rationale": "."}),
        dry_run=True,
        logs_root=tmp_path,
    )
    runs = list((tmp_path / "curator").iterdir())
    report = (runs[0] / "REPORT.md").read_text(encoding="utf-8")
    assert "(dry-run)" in report


def test_writes_fork_stdout_log_when_present(tmp_path: Path) -> None:
    write_run(
        SimpleNamespace(),
        _fork(stdout="some fork chatter", stderr="warning here"),
        _parsed({"skill": "x", "decision": "KEEP_AS_IS", "target": None, "rationale": "."}),
        logs_root=tmp_path,
    )
    run_dir = next((tmp_path / "curator").iterdir())
    assert (run_dir / "fork-stdout.log").read_text(encoding="utf-8") == "some fork chatter"
    assert (run_dir / "fork-stderr.log").read_text(encoding="utf-8") == "warning here"


def test_empty_runs_render_cleanly(tmp_path: Path) -> None:
    write_run(SimpleNamespace(), _fork(), _parsed(), logs_root=tmp_path)
    runs = list((tmp_path / "curator").iterdir())
    report = (runs[0] / "REPORT.md").read_text(encoding="utf-8")
    assert "(none)" in report


def test_absorptions_recorded_in_run_json(tmp_path: Path) -> None:
    """Reference migration cron needs `absorbed → umbrella` mapping
    persisted, not just decision_counts."""
    parsed = _parsed(
        {
            "skill": "narrow-a",
            "decision": "CONSOLIDATE_INTO",
            "target": "broad-umbrella",
            "absorbed_into": "broad-umbrella",
            "rationale": "merge",
        },
        {
            "skill": "narrow-b",
            "decision": "DEMOTE_TO_REFERENCES",
            "target": "broad-umbrella",
            "absorbed_into": "broad-umbrella",
            "rationale": "ref",
        },
        {
            "skill": "narrow-c",
            "decision": "PRUNE",
            "target": None,
            "absorbed_into": None,
            "rationale": "stale",
        },
    )
    write_run(SimpleNamespace(), _fork(), parsed, logs_root=tmp_path)
    run_dir = next((tmp_path / "curator").iterdir())
    data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert data["absorptions"] == {"broad-umbrella": ["narrow-a", "narrow-b"]}


def test_absorptions_section_appears_in_markdown(tmp_path: Path) -> None:
    parsed = _parsed(
        {
            "skill": "old",
            "decision": "CONSOLIDATE_INTO",
            "target": "umbrella",
            "absorbed_into": "umbrella",
            "rationale": "x",
        },
    )
    write_run(SimpleNamespace(), _fork(), parsed, logs_root=tmp_path)
    run_dir = next((tmp_path / "curator").iterdir())
    report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "Absorptions" in report
    assert "`old` → `umbrella`" in report


def test_no_absorptions_section_when_no_absorbed_into(tmp_path: Path) -> None:
    parsed = _parsed(
        {
            "skill": "x",
            "decision": "KEEP_AS_IS",
            "target": None,
            "absorbed_into": None,
            "rationale": ".",
        },
    )
    write_run(SimpleNamespace(), _fork(), parsed, logs_root=tmp_path)
    run_dir = next((tmp_path / "curator").iterdir())
    report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "Absorptions" not in report


def test_demote_decisions_render_in_report(tmp_path: Path) -> None:
    parsed = _parsed(
        {
            "skill": "fixture-snip",
            "decision": "DEMOTE_TO_SCRIPTS",
            "target": "testing-patterns",
            "absorbed_into": "testing-patterns",
            "rationale": "repeatable",
        },
    )
    write_run(SimpleNamespace(), _fork(), parsed, logs_root=tmp_path)
    run_dir = next((tmp_path / "curator").iterdir())
    report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "DEMOTE_TO_SCRIPTS" in report
    assert "testing-patterns" in report
