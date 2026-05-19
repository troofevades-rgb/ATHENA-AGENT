"""APScheduler-backed cron with SQLite persistence.

The scheduler instance is a thin wrapper:
- :class:`BackgroundScheduler` runs jobs on a thread pool independent of
  the foreground REPL.
- :class:`SQLAlchemyJobStore` persists the trigger state across daemon
  restarts (the JobStore in :mod:`athena.cron.jobs` persists the CronJob
  records themselves).

Watchdog vs agent dispatch is decided at ``add_job`` time by importing
the right runner. The runner gets the bare job dict; it re-loads the
:class:`CronJob` from the store before executing so the scheduler doesn't
have to keep stateful references to dataclasses.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .jobs import CronJob, JobStore

logger = logging.getLogger(__name__)


def _resolve_runner(mode: str) -> Callable[[str], None]:
    """Lazy import: dispatch the job back to the right runner by mode.

    Returns a top-level callable so APScheduler can serialize the job
    target name (closures aren't picklable for the SQLAlchemy jobstore).
    """
    if mode == "watchdog":
        from .watchdog import run_watchdog_job_by_id

        return run_watchdog_job_by_id
    from .runner import run_agent_job_by_id

    return run_agent_job_by_id


class CronScheduler:
    """Wraps a single :class:`BackgroundScheduler` plus the metadata store.

    The scheduler db (APScheduler) and the jobs db (CronJob metadata) are
    distinct files so a corruption in one doesn't take the other with it.
    """

    def __init__(self, db_path: Path, *, jobs_db_path: Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs_db_path = jobs_db_path or self.db_path.with_name("cron_jobs.db")
        self.store = JobStore(self.jobs_db_path)
        self._sched = BackgroundScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(url=f"sqlite:///{self.db_path}"),
            }
        )
        self._started = False

    # ---- Lifecycle ----

    def start(self) -> None:
        if self._started:
            return
        self._sched.start()
        self._started = True
        # Re-register every persisted job into the APScheduler instance.
        for job in self.store.list_jobs():
            if job.enabled:
                self._register(job)

    def stop(self) -> None:
        if not self._started:
            return
        self._sched.shutdown(wait=False)
        self._started = False

    # ---- CRUD ----

    def add_job(self, job: CronJob) -> CronJob:
        """Persist and (if enabled and started) register a new job."""
        self.store.upsert(job)
        if self._started and job.enabled:
            self._register(job)
        return job

    def remove_job(self, job_id: str) -> bool:
        existed = self.store.delete(job_id)
        try:
            self._sched.remove_job(job_id)
        except Exception:
            # Not registered with APScheduler — fine, we still removed the
            # metadata record.
            pass
        return existed

    def enable(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if job is None:
            return False
        job.enabled = True
        self.store.upsert(job)
        if self._started:
            self._register(job)
        return True

    def disable(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if job is None:
            return False
        job.enabled = False
        self.store.upsert(job)
        try:
            self._sched.remove_job(job_id)
        except Exception:
            pass
        return True

    def list_jobs(self) -> list[CronJob]:
        return self.store.list_jobs()

    def get_job(self, job_id: str) -> CronJob | None:
        return self.store.get(job_id)

    def next_run_time(self, job_id: str):
        """Return the APScheduler-computed next-run time, or None."""
        job = self._sched.get_job(job_id)
        return job.next_run_time if job else None

    # ---- Internals ----

    def _register(self, job: CronJob) -> None:
        target = _resolve_runner(job.mode)
        try:
            trigger = CronTrigger.from_crontab(job.cron_expr)
        except Exception as e:
            logger.error(
                "cron %s: invalid cron expression %r — %s",
                job.id,
                job.cron_expr,
                e,
            )
            raise
        self._sched.add_job(
            target,
            trigger=trigger,
            args=[job.id],
            id=job.id,
            replace_existing=True,
            misfire_grace_time=None,  # let late jobs still run on resume
        )
