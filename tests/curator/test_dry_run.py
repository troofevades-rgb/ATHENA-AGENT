"""Tests for curator dry-run behavior and the `athena curator` CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from athena.agent.fork import ForkResult
from athena.config import Config, CuratorConfig
from athena.curator import dry_run as dry_run_mod
from athena.curator import orchestrator, state

VALID = """\
```yaml-curator-report
runs:
  - skill: a
    decision: KEEP_AS_IS
    target: null
    rationale: ok
```
"""


def _agent(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "CONFIG_DIR", tmp_path)
    cfg = Config()
    cfg.curator = CuratorConfig(interval_hours=168, min_idle_hours=2, max_iterations=9)
    store = MagicMock()
    store.most_recent_other_session.return_value = None
    return SimpleNamespace(
        cfg=cfg,
        session_id="sid",
        session_store=store,
        workspace=tmp_path,
        client=None,
        model="qwen",
    )


def _patch_fork(monkeypatch, response: str):
    calls: list = []

    def fake_fork(parent, **kwargs):
        calls.append(kwargs)
        return ForkResult(
            final_response=response,
            duration_s=0.5,
            child_session_id="child-1",
        )

    monkeypatch.setattr("athena.agent.fork.fork", fake_fork)
    return calls


def test_dry_run_creates_report(monkeypatch, tmp_path) -> None:
    agent = _agent(monkeypatch, tmp_path)
    _patch_fork(monkeypatch, VALID)
    summary = orchestrator.maybe_run_curator(agent, force=True, dry_run=True)
    assert summary is not None
    assert summary["dry_run"] is True
    # REPORT.md exists under <tmp_path>/logs/curator/<stamp>/
    runs = list((tmp_path / "logs" / "curator").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "REPORT.md").exists()


def test_dry_run_does_not_modify_skills(monkeypatch, tmp_path) -> None:
    """The dry-run path must not touch <skills_root> (no .curator_state mutations
    on rejection-style flows, no skill writes)."""
    agent = _agent(monkeypatch, tmp_path)
    _patch_fork(monkeypatch, VALID)
    orchestrator.maybe_run_curator(agent, force=True, dry_run=True)
    # State should still update last_run_at (we did run, just in dry-run mode)
    # but no skill files were created.
    skills_dir = tmp_path / "skills"
    assert not any(skills_dir.glob("*/SKILL.md")) if skills_dir.exists() else True


def test_dry_run_writes_to_logs_curator_directory(monkeypatch, tmp_path) -> None:
    agent = _agent(monkeypatch, tmp_path)
    _patch_fork(monkeypatch, VALID)
    summary = orchestrator.maybe_run_curator(agent, force=True, dry_run=True)
    assert "logs" in summary["report_path"]
    assert "curator" in summary["report_path"]


def test_is_dry_run_addendum_helper() -> None:
    from athena.curator.prompts import CURATOR_REVIEW_PROMPT, DRY_RUN_BANNER

    assert dry_run_mod.is_dry_run_addendum(DRY_RUN_BANNER + CURATOR_REVIEW_PROMPT)
    assert not dry_run_mod.is_dry_run_addendum(CURATOR_REVIEW_PROMPT)


def test_cli_status_reads_state(tmp_path) -> None:
    from athena.cli.curator import main

    skills_root = tmp_path / "skills"
    state.write_state(
        skills_root,
        state.State(
            last_run_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            run_count=3,
            paused=True,
        ),
    )
    rc = main(["--home", str(tmp_path), "status"])
    assert rc == 0


def test_cli_pause_resume_round_trip(tmp_path) -> None:
    from athena.cli.curator import main

    main(["--home", str(tmp_path), "pause"])
    s = state.read_state(tmp_path / "skills")
    assert s.paused is True
    main(["--home", str(tmp_path), "resume"])
    s = state.read_state(tmp_path / "skills")
    assert s.paused is False


def test_cli_inspect_last_prints_latest_report(tmp_path, capsys) -> None:
    # Manually plant a fake report.
    run_dir = tmp_path / "logs" / "curator" / "20260512-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "REPORT.md").write_text("# fake curator run\n", encoding="utf-8")

    from athena.cli.curator import main

    rc = main(["--home", str(tmp_path), "inspect-last"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fake curator run" in out
