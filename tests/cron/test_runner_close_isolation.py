"""0.3.0 hardening tier 1 (C) -- cron close failures don't clobber success.

``run_agent_job`` runs an LLM-driven turn, builds a success ``result``
dict, and then calls ``agent.close()`` in the inner ``finally``. If
``close()`` raises -- e.g. a plugin teardown hook misbehaves on a
gateway-pooled session -- the exception used to propagate to the
outer ``except Exception`` block, which overwrote ``result`` and
``status`` with error info. The cron job was actually successful but
got reported as a failure.

The fix wraps ``agent.close()`` in its own try/except with
``logger.exception`` so cleanup errors stay observable in the log
without changing the job's reported outcome.

Pins:

  * Run succeeds + close raises -> ``result["status"] == "success"``
    and the canned ``last_assistant_message`` is preserved.
  * The close failure is logged via ``logger.exception`` (traceback
    attached) so the operator can still diagnose the bad teardown.
  * Run fails AND close raises -> the run failure is what gets
    reported (the original error path still wins); the close error
    becomes a secondary log line.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import athena.cron.runner as runner_mod
from athena.cron.jobs import CronJob, JobStore


class _FakeAgentCloseRaises:
    """run_until_done succeeds; close() raises."""

    last_instance: _FakeAgentCloseRaises | None = None

    def __init__(self, cfg: object, workspace: Path, **_kw: object) -> None:
        self.cfg = cfg
        self.workspace = workspace
        _FakeAgentCloseRaises.last_instance = self

    def run_until_done(self, prompt: str, *, max_iterations: int = 16) -> None:
        # The run is fine; the bug is in shutdown.
        pass

    def last_assistant_message(self) -> str:
        return "successful response"

    def tool_call_trace(self) -> list[dict[str, object]]:
        return []

    def close(self) -> None:
        raise RuntimeError("plugin teardown blew up")


class _FakeAgentRunRaises:
    """run_until_done raises (real failure); close() also raises."""

    def __init__(self, cfg: object, workspace: Path, **_kw: object) -> None:
        pass

    def run_until_done(self, prompt: str, *, max_iterations: int = 16) -> None:
        raise ValueError("model API rejected the request")

    def last_assistant_message(self) -> str:
        return ""

    def tool_call_trace(self) -> list[dict[str, object]]:
        return []

    def close(self) -> None:
        raise RuntimeError("close also raised")


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "cron_jobs.db")


def _job(tmp_path: Path) -> CronJob:
    return CronJob(
        cron_expr="* * * * *",
        mode="agent",
        prompt="check things",
        delivery_target=f"file:{tmp_path / 'out.jsonl'}",
    )


def test_close_failure_does_not_clobber_success(
    monkeypatch: pytest.MonkeyPatch,
    store: JobStore,
    tmp_path: Path,
) -> None:
    """The bug: previously, a raising agent.close() escaped the inner
    finally and was caught by the outer ``except Exception``, which
    overwrote the success result with an error payload. After the
    fix, the success result survives."""
    import athena.agent

    monkeypatch.setattr(athena.agent, "Agent", _FakeAgentCloseRaises)
    job = _job(tmp_path)
    store.upsert(job)

    result = runner_mod.run_agent_job(job, store=store)

    assert result["status"] == "success", f"close() failure clobbered the successful run: {result}"
    assert result["response"] == "successful response"
    # And the started_at field is still the success-path one (the
    # error path would have overwritten it too, but only as a
    # symptom; the real check is on status).
    assert "started_at" in result


def test_close_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    store: JobStore,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cleanup errors are observable -- ``logger.exception`` fires
    so operators can still see the close failure in the cron log
    even though the job is reported as success."""
    import athena.agent

    monkeypatch.setattr(athena.agent, "Agent", _FakeAgentCloseRaises)
    job = _job(tmp_path)
    store.upsert(job)

    with caplog.at_level(logging.ERROR, logger="athena.cron.runner"):
        runner_mod.run_agent_job(job, store=store)

    matches = [r for r in caplog.records if "agent.close()" in r.getMessage()]
    assert len(matches) >= 1, (
        f"expected agent.close() failure log; got {[r.getMessage() for r in caplog.records]}"
    )
    # exc_info attached -- the traceback survives so an aggregator
    # can extract the stack.
    assert matches[0].exc_info is not None


def test_run_failure_still_wins_when_close_also_raises(
    monkeypatch: pytest.MonkeyPatch,
    store: JobStore,
    tmp_path: Path,
) -> None:
    """When the run itself raises AND close raises, the run failure
    is what the cron job reports (it's the real fault). The close
    error becomes a secondary log line, not the reported reason."""
    import athena.agent

    monkeypatch.setattr(athena.agent, "Agent", _FakeAgentRunRaises)
    job = _job(tmp_path)
    store.upsert(job)

    result = runner_mod.run_agent_job(job, store=store)

    assert result["status"] == "error"
    # The reported reason is the *run* failure, not the close
    # failure -- the run error is the primary fault.
    assert "ValueError" in result["reason"]
    assert "model API rejected" in result["reason"]
