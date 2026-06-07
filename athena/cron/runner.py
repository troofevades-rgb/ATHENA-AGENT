"""Agent mode — full LLM-driven turn for a scheduled job.

Constructs a minimal :class:`Agent` against the default profile and
runs a single turn to completion (capped at 20 iterations). The prompt
is either:

- ``"Run the {skill} skill. ..."`` if ``job.skill`` is set,
- ``job.prompt`` if explicit prompt is provided.

The final assistant message and tool-call trace are passed to delivery.
The full Agent lifecycle (session store, plugins, etc.) runs as in any
foreground session, but with ``write_origin="cron"`` so the curator can
distinguish cron-driven writes from foreground ones in a future phase.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .delivery import deliver
from .jobs import CronJob, JobStore

logger = logging.getLogger(__name__)


_AGENT_MAX_ITERATIONS = 20


def run_agent_job_by_id(job_id: str, *, jobs_db_path: Path | None = None) -> None:
    """Look up the CronJob by ID and run it. Used by APScheduler so the
    target stays picklable across daemon restarts.

    Resolves the jobs DB through the same profile-aware helper the CLI
    uses (`athena.cli.cron._profile_cron_paths`). Previously hardcoded
    ``CONFIG_DIR / cron_jobs.db``, which silently looked at an empty
    legacy location after the profile migration moved the live DB to
    ``profiles/<profile>/``.
    """
    if jobs_db_path is None:
        from ..cli.cron import _profile_cron_paths

        _, jobs_db_path = _profile_cron_paths()
    store = JobStore(Path(jobs_db_path))
    job = store.get(job_id)
    if job is None:
        logger.warning("agent cron: job %s not found in store; skipping", job_id)
        return
    run_agent_job(job, store=store)


def run_agent_job(job: CronJob, *, store: JobStore | None = None) -> dict[str, Any]:
    """Build an Agent, run one turn, deliver the result. Returns the
    delivered dict so callers (tests, run-now) can inspect it.
    """
    if not (job.skill or job.prompt):
        result: dict[str, Any] = {
            "status": "error",
            "reason": "agent job has no skill or prompt",
        }
        if store:
            store.record_run(job.id, status="error")
        deliver(job, result)
        return result

    start = datetime.now(timezone.utc)
    prompt = _build_prompt(job)

    # Lazy imports — pulling Agent at module load time would force the
    # rest of the cron package to drag in httpx + the whole agent stack
    # just to construct a CronJob.
    from ..agent import Agent
    from ..config import load_config
    from ..provenance import CRON
    from ..safety.thread_entry import non_foreground_thread

    # non_foreground_thread: write-origin=CRON + AUTO_DENY + fresh
    # approval scope. Without AUTO_DENY a confirmation-required tool
    # (Bash outside the allowlist, etc.) would call ui.confirm from an
    # APScheduler daemon with no stdin and block indefinitely.
    with non_foreground_thread(origin=CRON):
        try:
            cfg = load_config()
            agent = Agent(cfg, Path.cwd())
            try:
                agent.run_until_done(prompt, max_iterations=_AGENT_MAX_ITERATIONS)
                result = {
                    "status": "success",
                    "response": agent.last_assistant_message(),
                    "tool_calls": agent.tool_call_trace(),
                    "started_at": start.isoformat(),
                }
                status = "success"
            finally:
                # Don't let agent.close() failures clobber a successful run
                # by escaping to the outer except. Cleanup errors are
                # logged but don't change the cron job's reported outcome.
                try:
                    agent.close()
                except Exception:
                    logger.exception("agent.close() raised in cron job %s", job.id)
        except Exception as e:
            logger.exception("agent cron %s failed", job.id)
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


def _build_prompt(job: CronJob) -> str:
    if job.skill:
        ctx = f" Context: {job.description}" if job.description else ""
        return f"Run the {job.skill} skill.{ctx}"
    return job.prompt or ""
