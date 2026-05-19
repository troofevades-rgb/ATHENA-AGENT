"""End-to-end tests for ``athena cron`` CLI subcommands."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import athena.cli.cron as cron_cli
from athena.cron.jobs import JobStore


@pytest.fixture
def cli_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """Redirect the CLI's default scheduler + jobs DB to tmp_path."""
    sched_db = tmp_path / "scheduler.db"
    jobs_db = tmp_path / "cron_jobs.db"
    monkeypatch.setattr(cron_cli, "_default_paths", lambda: (sched_db, jobs_db))
    return sched_db, jobs_db


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = cron_cli.main(argv)
        except SystemExit as e:
            # argparse / explicit SystemExit('error: ...') both flow through here.
            if isinstance(e.code, str):
                err.write(e.code + "\n")
                rc = 2
            else:
                rc = int(e.code or 0)
    return rc, out.getvalue(), err.getvalue()


def test_add_watchdog_job(cli_paths):
    rc, stdout, _ = _run(
        [
            "add",
            "--schedule",
            "* * * * *",
            "--script",
            "echo hi",
            "--description",
            "test script",
        ]
    )
    assert rc == 0
    assert "added cron job" in stdout
    # Job is in the store.
    store = JobStore(cli_paths[1])
    assert len(store.list_jobs()) == 1
    assert store.list_jobs()[0].mode == "watchdog"


def test_add_agent_prompt_job(cli_paths):
    rc, _, _ = _run(
        [
            "add",
            "--schedule",
            "0 9 * * *",
            "--prompt",
            "morning status",
        ]
    )
    assert rc == 0
    job = JobStore(cli_paths[1]).list_jobs()[0]
    assert job.mode == "agent"
    assert job.prompt == "morning status"


def test_add_rejects_missing_target(cli_paths):
    rc, _, err = _run(["add", "--schedule", "* * * * *"])
    assert rc != 0
    assert "skill" in err or "prompt" in err or "script" in err


def test_add_rejects_script_with_prompt(cli_paths):
    rc, _, err = _run(
        [
            "add",
            "--schedule",
            "* * * * *",
            "--script",
            "echo x",
            "--prompt",
            "y",
        ]
    )
    assert rc != 0
    assert "mutually exclusive" in err


def test_list_empty(cli_paths):
    rc, stdout, _ = _run(["list"])
    assert rc == 0
    assert "no cron jobs" in stdout


def test_list_shows_jobs(cli_paths):
    _run(["add", "--schedule", "* * * * *", "--script", "echo a"])
    _run(["add", "--schedule", "0 9 * * *", "--prompt", "report"])
    rc, stdout, _ = _run(["list"])
    assert rc == 0
    assert "watchdog" in stdout
    assert "agent" in stdout


def test_remove_by_prefix(cli_paths):
    _run(["add", "--schedule", "* * * * *", "--script", "echo a"])
    job = JobStore(cli_paths[1]).list_jobs()[0]
    rc, stdout, _ = _run(["remove", job.id[:8]])
    assert rc == 0
    assert job.id in stdout
    assert JobStore(cli_paths[1]).list_jobs() == []


def test_remove_unknown_id(cli_paths):
    rc, _, err = _run(["remove", "definitely-not-a-real-id"])
    assert rc != 0
    assert "no job matching" in err


def test_disable_then_enable(cli_paths):
    _run(["add", "--schedule", "* * * * *", "--prompt", "x"])
    job = JobStore(cli_paths[1]).list_jobs()[0]
    rc, _, _ = _run(["disable", job.id])
    assert rc == 0
    assert JobStore(cli_paths[1]).get(job.id).enabled is False
    rc, _, _ = _run(["enable", job.id])
    assert rc == 0
    assert JobStore(cli_paths[1]).get(job.id).enabled is True


def test_run_now_watchdog(cli_paths):
    _run(
        [
            "add",
            "--schedule",
            "* * * * *",
            "--script",
            f"{sys.executable} -c \"print('hello')\"",
        ]
    )
    job = JobStore(cli_paths[1]).list_jobs()[0]
    rc, stdout, _ = _run(["run-now", job.id])
    assert rc == 0
    assert "success" in stdout


def test_logs_shows_status(cli_paths):
    _run(["add", "--schedule", "* * * * *", "--script", f'{sys.executable} -c "pass"'])
    job = JobStore(cli_paths[1]).list_jobs()[0]
    _run(["run-now", job.id])
    rc, stdout, _ = _run(["logs", job.id])
    assert rc == 0
    assert "success" in stdout


def test_daemon_once_starts_and_exits(cli_paths):
    _run(["add", "--schedule", "* * * * *", "--prompt", "x"])
    rc, stdout, _ = _run(["daemon", "--once"])
    assert rc == 0
    assert "daemon started" in stdout
