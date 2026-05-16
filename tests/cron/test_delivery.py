"""Cron delivery routing: log, file, gateway-stub, unknown."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ocode.cron.delivery import deliver
from ocode.cron.jobs import CronJob


def _job(target: str) -> CronJob:
    return CronJob(
        cron_expr="* * * * *",
        mode="watchdog",
        script="echo x",
        description="test",
        delivery_target=target,
    )


def test_log_delivery(caplog):
    job = _job("log")
    with caplog.at_level(logging.INFO, logger="ocode.cron"):
        deliver(job, {"status": "success", "exit_code": 0})
    msgs = [r.message for r in caplog.records]
    assert any(job.id in m and "success" in m for m in msgs)


def test_file_delivery_writes_to_path(tmp_path: Path):
    target = tmp_path / "out.jsonl"
    job = _job(f"file:{target}")
    deliver(job, {"status": "success", "stdout": "hello"})
    line = target.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["status"] == "success"
    assert record["stdout"] == "hello"
    assert record["job_id"] == job.id
    assert "timestamp" in record


def test_file_delivery_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "out.jsonl"
    job = _job(f"file:{target}")
    deliver(job, {"status": "success"})
    assert target.exists()


def test_file_delivery_appends_existing_content(tmp_path: Path):
    target = tmp_path / "appended.jsonl"
    job = _job(f"file:{target}")
    deliver(job, {"status": "success", "n": 1})
    deliver(job, {"status": "success", "n": 2})
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["n"] == 1
    assert json.loads(lines[1])["n"] == 2


def test_gateway_delivery_logs_warning_and_falls_back(caplog):
    job = _job("gateway://telegram/12345")
    with caplog.at_level(logging.WARNING, logger="ocode.cron"):
        deliver(job, {"status": "success"})
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("gateway" in r.message.lower() for r in warnings)


def test_unknown_target_falls_back_to_log(caplog):
    job = _job("not-a-real-target://oops")
    with caplog.at_level(logging.WARNING, logger="ocode.cron"):
        deliver(job, {"status": "success"})
    msgs = [r.message for r in caplog.records]
    assert any("unknown delivery target" in m for m in msgs)


def test_delivery_failure_is_swallowed(monkeypatch, caplog):
    """A delivery error must not propagate — cron is best-effort."""
    job = _job("file:/this/cannot/exist/because/we/will/break/it")

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("ocode.cron.delivery._deliver_file", boom)
    with caplog.at_level(logging.WARNING, logger="ocode.cron"):
        deliver(job, {"status": "success"})  # must not raise
    assert any("delivery failed" in r.message for r in caplog.records)
