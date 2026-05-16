"""Watchdog runner: subprocess execution, capture, timeout, status update."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ocode.cron.jobs import CronJob, JobStore
from ocode.cron.watchdog import run_watchdog_job


def _job(script: str, *, target: str = "log") -> CronJob:
    return CronJob(
        cron_expr="* * * * *",
        mode="watchdog",
        script=script,
        delivery_target=target,
    )


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "cron_jobs.db")


def test_runs_script_with_subprocess(store: JobStore, tmp_path: Path):
    target = tmp_path / "wd.jsonl"
    job = _job(f'{sys.executable} -c "print(\'hello\')"', target=f"file:{target}")
    store.upsert(job)
    result = run_watchdog_job(job, store=store)
    assert result["status"] == "success"
    assert "hello" in result["stdout"]
    # Result was also delivered to the file:
    record = json.loads(target.read_text(encoding="utf-8").strip())
    assert record["status"] == "success"


def test_returns_exit_code_zero_as_success(store: JobStore):
    job = _job(f'{sys.executable} -c "import sys; sys.exit(0)"')
    store.upsert(job)
    result = run_watchdog_job(job, store=store)
    assert result["status"] == "success"
    assert result["exit_code"] == 0


def test_nonzero_exit_marks_error(store: JobStore):
    job = _job(f'{sys.executable} -c "import sys; sys.exit(3)"')
    store.upsert(job)
    result = run_watchdog_job(job, store=store)
    assert result["status"] == "error"
    assert result["exit_code"] == 3


def test_captures_stdout_and_stderr(store: JobStore):
    job = _job(
        f'{sys.executable} -c "import sys; '
        f'print(\'out\'); print(\'err\', file=sys.stderr)"'
    )
    store.upsert(job)
    result = run_watchdog_job(job, store=store)
    assert "out" in result["stdout"]
    assert "err" in result["stderr"]


def test_timeout_marks_error(store: JobStore, monkeypatch):
    """A very short timeout should surface as status=error."""
    import ocode.cron.watchdog as wd
    monkeypatch.setattr(wd, "_DEFAULT_TIMEOUT_S", 1)
    # Sleep longer than the timeout. Use python -c for portability.
    job = _job(f'{sys.executable} -c "import time; time.sleep(10)"')
    store.upsert(job)
    result = run_watchdog_job(job, store=store)
    assert result["status"] == "error"
    assert "timeout" in result["reason"].lower()


def test_record_run_updates_last_status(store: JobStore):
    job = _job(f'{sys.executable} -c "import sys; sys.exit(0)"')
    store.upsert(job)
    run_watchdog_job(job, store=store)
    fetched = store.get(job.id)
    assert fetched.last_status == "success"
    assert fetched.last_run_at is not None


def test_missing_script_marks_error(store: JobStore):
    """An agent-mode CronJob smuggled through watchdog (no script) errors clean."""
    # We can't construct a watchdog CronJob without a script, so build a
    # plain object that mimics one:
    class _FakeJob:
        id = "fake"
        script = None
        delivery_target = "log"
        description = ""
    result = run_watchdog_job(_FakeJob(), store=None)
    assert result["status"] == "error"


def test_output_is_truncated(store: JobStore, monkeypatch):
    """Large stdout is truncated at the configured cap, not unbounded."""
    import ocode.cron.watchdog as wd
    monkeypatch.setattr(wd, "_OUTPUT_TRUNC", 100)
    # Emit 1000 characters of output.
    job = _job(f'{sys.executable} -c "print(\'x\' * 1000)"')
    store.upsert(job)
    result = run_watchdog_job(job, store=store)
    assert len(result["stdout"]) == 100
