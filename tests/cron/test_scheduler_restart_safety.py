"""Restart-safety tests for ``CronScheduler``.

The existing tests/cron/test_scheduler.py covers happy-path persistence
across restart. What's not covered: what happens when a persisted job
record becomes invalid between save and restart — bad cron_expr, missing
runner mode, etc. With the current code (athena/cron/scheduler.py:67-75),
``start()`` blindly re-registers every enabled job; a single corrupt
record raises out of ``_register`` and takes the WHOLE scheduler down,
losing every other valid job in the process.

This is the worst kind of cron failure: invisible until restart, then
total. These tests pin the current behavior so any future "swallow and
log" fix has an obvious place to verify the change.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from athena.cron.jobs import CronJob
from athena.cron.scheduler import CronScheduler


def _corrupt_cron_expr(jobs_db: Path, job_id: str, bad_expr: str) -> None:
    """Bypass the dataclass to push an invalid cron_expr into the
    persisted record. Simulates: schema drift, manual DB edit, or
    APScheduler version upgrade tightening cron parsing."""
    with sqlite3.connect(jobs_db) as conn:
        cur = conn.execute(
            "UPDATE cron_jobs SET cron_expr = ? WHERE id = ?",
            (bad_expr, job_id),
        )
        assert cur.rowcount == 1, f"failed to corrupt job {job_id}"


def test_restart_with_corrupted_cron_expr_skips_with_warning(
    tmp_path: Path, caplog,
) -> None:
    """If the persisted cron_expr becomes unparseable, restart must
    log a warning and skip that job — not raise (which would take
    down EVERY other job too).

    Pinned behavior (was: re-raise blast radius; now: skip + log)."""
    import logging
    db = tmp_path / "scheduler.db"
    jobs_db = tmp_path / "cron_jobs.db"

    s1 = CronScheduler(db_path=db, jobs_db_path=jobs_db)
    s1.start()
    good = CronJob(cron_expr="0 9 * * *", mode="agent", prompt="ok")
    s1.add_job(good)
    s1.stop()

    _corrupt_cron_expr(jobs_db, good.id, "not a valid cron")

    s2 = CronScheduler(db_path=db, jobs_db_path=jobs_db)
    with caplog.at_level(logging.ERROR, logger="athena.cron.scheduler"):
        s2.start()  # MUST NOT raise
    # Failure surfaced via log so an operator can find it
    assert any(
        "failed to register at startup" in rec.message
        for rec in caplog.records
    ), "corrupt cron silently skipped — no log record visible to operator"
    # Metadata record still there so the user can fix it via CLI
    assert s2.store.get(good.id) is not None
    s2.stop()


def test_corrupt_record_does_not_swallow_valid_jobs_metadata(
    tmp_path: Path,
) -> None:
    """Even when one record is corrupt and trips ``start()``, the
    persisted metadata for ALL jobs (good and bad) must remain
    intact and queryable via the JobStore. Operators need this so
    they can list, inspect, and fix the bad job from the CLI
    without losing visibility into the rest.

    (We deliberately do NOT assert which jobs got registered with
    APScheduler — that depends on iteration order which is keyed
    by created_at and not load-bearing for users.)"""
    db = tmp_path / "scheduler.db"
    jobs_db = tmp_path / "cron_jobs.db"

    s1 = CronScheduler(db_path=db, jobs_db_path=jobs_db)
    s1.start()
    good_a = CronJob(cron_expr="0 9 * * *", mode="agent", prompt="A")
    bad = CronJob(cron_expr="* * * * *", mode="agent", prompt="B")
    good_c = CronJob(cron_expr="0 10 * * *", mode="agent", prompt="C")
    s1.add_job(good_a)
    s1.add_job(bad)
    s1.add_job(good_c)
    s1.stop()

    _corrupt_cron_expr(jobs_db, bad.id, "not_a_cron")

    s2 = CronScheduler(db_path=db, jobs_db_path=jobs_db)
    try:
        s2.start()
    except Exception:
        pass
    # All three records remain inspectable, regardless of whether
    # APScheduler registration succeeded for any of them
    all_ids = {j.id for j in s2.list_jobs()}
    assert good_a.id in all_ids
    assert bad.id in all_ids
    assert good_c.id in all_ids
    s2.stop()


def test_disabled_corrupt_job_does_not_block_startup(tmp_path: Path) -> None:
    """A corrupted-but-disabled job must NOT prevent startup. The
    re-register loop at scheduler.py:73-75 explicitly checks
    ``if job.enabled``, so this is the workaround a user has when
    their scheduler won't start: disable the bad job in the DB."""
    db = tmp_path / "scheduler.db"
    jobs_db = tmp_path / "cron_jobs.db"

    s1 = CronScheduler(db_path=db, jobs_db_path=jobs_db)
    s1.start()
    bad = CronJob(
        cron_expr="0 9 * * *", mode="agent", prompt="x", enabled=False,
    )
    s1.add_job(bad)
    s1.stop()

    _corrupt_cron_expr(jobs_db, bad.id, "garbage")

    s2 = CronScheduler(db_path=db, jobs_db_path=jobs_db)
    # MUST start cleanly because the bad job is disabled
    s2.start()
    try:
        # And the metadata is still readable for fix-up
        rec = s2.get_job(bad.id)
        assert rec is not None
        assert rec.enabled is False
        assert rec.cron_expr == "garbage"
    finally:
        s2.stop()
