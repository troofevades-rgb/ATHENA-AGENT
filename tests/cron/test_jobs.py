"""CronJob dataclass + JobStore persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from athena.cron.jobs import CronJob, JobStore

# ---- CronJob dataclass --------------------------------------------------


def test_cron_job_dataclass_defaults():
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="hello")
    assert job.id  # uuid auto-assigned
    assert job.mode == "agent"
    assert job.prompt == "hello"
    assert job.enabled is True
    assert job.created_at.tzinfo is not None  # UTC


def test_cron_job_round_trips_json():
    original = CronJob(
        cron_expr="0 9 * * *",
        mode="watchdog",
        description="daily ping",
        script="ping -c 1 example.com",
        delivery_target="file:/tmp/ping.log",
        last_run_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        last_status="success",
    )
    blob = original.to_json()
    parsed = json.loads(blob)
    assert parsed["mode"] == "watchdog"
    round_tripped = CronJob.from_json(blob)
    assert round_tripped.id == original.id
    assert round_tripped.cron_expr == original.cron_expr
    assert round_tripped.script == original.script
    assert round_tripped.last_run_at == original.last_run_at


def test_cron_job_rejects_invalid_mode():
    with pytest.raises(ValueError, match="invalid cron mode"):
        CronJob(cron_expr="* * * * *", mode="bogus", prompt="x")


def test_watchdog_mode_requires_script():
    with pytest.raises(ValueError, match="watchdog mode requires a script"):
        CronJob(cron_expr="* * * * *", mode="watchdog")


def test_agent_mode_requires_skill_or_prompt():
    with pytest.raises(ValueError, match="agent mode requires"):
        CronJob(cron_expr="* * * * *", mode="agent")


def test_agent_mode_accepts_skill_alone():
    CronJob(cron_expr="* * * * *", mode="agent", skill="my-skill")  # no exception


def test_agent_mode_accepts_prompt_alone():
    CronJob(cron_expr="* * * * *", mode="agent", prompt="hello")  # no exception


# ---- JobStore -----------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "cron_jobs.db")


def test_jobstore_upsert_and_get(store: JobStore):
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="x")
    store.upsert(job)
    fetched = store.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.prompt == "x"
    assert fetched.created_at == job.created_at


def test_jobstore_list_orders_by_created_at(store: JobStore):
    a = CronJob(
        cron_expr="* * * * *",
        mode="agent",
        prompt="a",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    b = CronJob(
        cron_expr="* * * * *",
        mode="agent",
        prompt="b",
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    store.upsert(b)
    store.upsert(a)
    listed = store.list_jobs()
    assert [j.prompt for j in listed] == ["a", "b"]


def test_jobstore_upsert_replaces_existing(store: JobStore):
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="v1")
    store.upsert(job)
    job.prompt = "v2"
    store.upsert(job)
    assert store.get(job.id).prompt == "v2"
    assert len(store.list_jobs()) == 1


def test_jobstore_delete(store: JobStore):
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="x")
    store.upsert(job)
    assert store.delete(job.id) is True
    assert store.get(job.id) is None
    assert store.delete(job.id) is False  # idempotent


def test_jobstore_record_run(store: JobStore):
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="x")
    store.upsert(job)
    when = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    store.record_run(job.id, status="success", when=when)
    fetched = store.get(job.id)
    assert fetched.last_status == "success"
    assert fetched.last_run_at == when


def test_jobstore_persists_across_reopen(tmp_path: Path):
    db_path = tmp_path / "cron_jobs.db"
    store1 = JobStore(db_path)
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="x")
    store1.upsert(job)
    # New JobStore on the same file sees the prior data.
    store2 = JobStore(db_path)
    assert store2.get(job.id) is not None
