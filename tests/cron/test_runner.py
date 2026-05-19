"""Agent-mode runner: prompt building, Agent invocation, delivery."""

from __future__ import annotations

from pathlib import Path

import pytest

import athena.cron.runner as runner_mod
from athena.cron.jobs import CronJob, JobStore


class _FakeAgent:
    """Records the prompt; returns a canned final response."""

    last_instance: _FakeAgent | None = None

    def __init__(self, cfg, workspace, **kwargs):
        self.cfg = cfg
        self.workspace = workspace
        self.received_prompt: str | None = None
        self._closed = False
        _FakeAgent.last_instance = self

    def run_until_done(self, prompt: str, *, max_iterations: int = 16) -> None:
        self.received_prompt = prompt

    def last_assistant_message(self) -> str:
        return "canned response"

    def tool_call_trace(self) -> list[dict]:
        return [{"function": {"name": "FakeTool", "arguments": "{}"}}]

    def close(self) -> None:
        self._closed = True


@pytest.fixture
def patched_agent(monkeypatch: pytest.MonkeyPatch):
    """Replace runner_mod's lazy Agent import with our fake."""
    _FakeAgent.last_instance = None
    import athena.agent

    monkeypatch.setattr(athena.agent, "Agent", _FakeAgent)
    # load_config still runs; it's harmless.
    return _FakeAgent


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "cron_jobs.db")


def test_agent_job_runs_skill_with_prompt(patched_agent, store: JobStore, tmp_path: Path):
    target = tmp_path / "out.jsonl"
    job = CronJob(
        cron_expr="* * * * *",
        mode="agent",
        skill="morning-status",
        description="daily status report",
        delivery_target=f"file:{target}",
    )
    store.upsert(job)
    result = runner_mod.run_agent_job(job, store=store)
    assert result["status"] == "success"
    assert "morning-status" in patched_agent.last_instance.received_prompt
    assert "daily status report" in patched_agent.last_instance.received_prompt
    assert result["response"] == "canned response"


def test_agent_job_uses_explicit_prompt_when_no_skill(
    patched_agent, store: JobStore, tmp_path: Path
):
    job = CronJob(
        cron_expr="* * * * *",
        mode="agent",
        prompt="check disk space and report",
    )
    store.upsert(job)
    runner_mod.run_agent_job(job, store=store)
    assert patched_agent.last_instance.received_prompt == "check disk space and report"


def test_agent_job_records_last_run(patched_agent, store: JobStore):
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="x")
    store.upsert(job)
    runner_mod.run_agent_job(job, store=store)
    fetched = store.get(job.id)
    assert fetched.last_status == "success"
    assert fetched.last_run_at is not None


def test_agent_job_records_error_on_exception(monkeypatch, store: JobStore):
    """If Agent construction or run raises, the job is recorded as error."""

    class _BrokenAgent:
        def __init__(self, cfg, workspace, **kwargs):
            raise RuntimeError("boom")

    import athena.agent

    monkeypatch.setattr(athena.agent, "Agent", _BrokenAgent)
    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="x")
    store.upsert(job)
    result = runner_mod.run_agent_job(job, store=store)
    assert result["status"] == "error"
    assert "boom" in result["reason"]
    assert store.get(job.id).last_status == "error"


def test_run_agent_job_by_id_executes(patched_agent, store: JobStore):
    """APScheduler entry point: re-loads job from store and runs it."""
    from athena.cron.runner import run_agent_job_by_id

    job = CronJob(cron_expr="* * * * *", mode="agent", prompt="hello")
    store.upsert(job)
    run_agent_job_by_id(job.id, jobs_db_path=store.db_path)
    assert patched_agent.last_instance.received_prompt == "hello"
    assert store.get(job.id).last_status == "success"


def test_run_agent_job_by_id_missing_id_is_silent(store: JobStore, caplog):
    import logging

    from athena.cron.runner import run_agent_job_by_id

    with caplog.at_level(logging.WARNING):
        run_agent_job_by_id("nope", jobs_db_path=store.db_path)
    assert any("not found" in r.message for r in caplog.records)


def test_agent_job_with_no_prompt_or_skill_errors_cleanly(store: JobStore):
    """Constructing the CronJob is rejected at the dataclass level — but
    if one slips through (e.g. legacy data), the runner returns an error
    rather than crashing."""

    class _FakeJob:
        id = "fake"
        skill = None
        prompt = None
        description = ""
        delivery_target = "log"

    result = runner_mod.run_agent_job(_FakeJob(), store=None)
    assert result["status"] == "error"
