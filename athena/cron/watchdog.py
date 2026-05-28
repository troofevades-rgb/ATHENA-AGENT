"""Watchdog mode — fixed shell script invocation, no LLM.

Cheap, predictable sentinel checks. The script is invoked via
:func:`subprocess.run` with a hard 300-second timeout. stdout, stderr,
and the exit code are captured and routed through :mod:`athena.cron.delivery`.

A watchdog job that needs to escalate to LLM analysis writes a file the
next agent-mode job picks up — there is no in-process handoff.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .delivery import deliver
from .jobs import JobStore

logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_S = 300
_OUTPUT_TRUNC = 8_192


def run_watchdog_job_by_id(job_id: str, *, jobs_db_path: Path | None = None) -> None:
    """Look up the CronJob by ID and run it. Used by APScheduler so the
    target stays picklable across daemon restarts.

    Resolves the jobs DB through the same profile-aware helper the CLI
    uses (`athena.cli.cron._profile_cron_paths`). Previously hardcoded
    ``CONFIG_DIR / cron_jobs.db``, which silently looked at an empty
    legacy location after the profile migration moved the live DB.
    """
    if jobs_db_path is None:
        from ..cli.cron import _profile_cron_paths
        _, jobs_db_path = _profile_cron_paths()
    store = JobStore(Path(jobs_db_path))
    job = store.get(job_id)
    if job is None:
        logger.warning("watchdog: job %s not found in store; skipping", job_id)
        return
    run_watchdog_job(job, store=store)


def run_watchdog_job(job, *, store: JobStore | None = None) -> dict:
    """Execute ``job.script`` as a shell command. Returns the result dict
    (also delivered via :func:`deliver` and recorded against the store).
    """
    if not job.script:
        result = {"status": "error", "reason": "watchdog job has no script"}
        if store:
            store.record_run(job.id, status="error")
        deliver(job, result)
        return result

    start = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            job.script,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_S,
        )
        status = "success" if completed.returncode == 0 else "error"
        result = {
            "status": status,
            "exit_code": completed.returncode,
            "stdout": (completed.stdout or "")[:_OUTPUT_TRUNC],
            "stderr": (completed.stderr or "")[:_OUTPUT_TRUNC],
            "started_at": start.isoformat(),
        }
    except subprocess.TimeoutExpired:
        result = {
            "status": "error",
            "reason": f"timeout after {_DEFAULT_TIMEOUT_S}s",
            "started_at": start.isoformat(),
        }
        status = "error"
    except Exception as e:
        result = {
            "status": "error",
            "reason": f"{type(e).__name__}: {e}",
            "started_at": start.isoformat(),
        }
        status = "error"

    if store:
        store.record_run(job.id, status=status)
    deliver(job, result)
    return result


def _default_jobs_db(config_dir) -> Path:
    """Default location for the cron jobs DB used when no override is passed.

    Lives next to the APScheduler db at ``<CONFIG_DIR>/cron_jobs.db``.
    """
    return Path(config_dir) / "cron_jobs.db"
