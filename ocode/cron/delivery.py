"""Cron output delivery routing.

Three delivery targets parsed from ``CronJob.delivery_target``:

- ``log`` — INFO log via the cron logger. Goes wherever stdlib logging
  goes (stderr by default; gateway daemon installs a file handler).
- ``file:<path>`` — append an ISO-timestamped JSON line to ``<path>``.
  Parent dirs are created. Existing content is preserved.
- ``gateway://<platform>/<chat_id>`` — Phase 10 gateway integration.
  For Phase 6 this logs a warning and skips.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .jobs import CronJob


logger = logging.getLogger("ocode.cron")


def deliver(job: "CronJob", result: dict[str, Any]) -> None:
    """Route ``result`` to the destination specified by ``job.delivery_target``.

    All exceptions are caught and logged at WARNING; delivery failure must
    never cascade into a cron job being marked failed (the JOB succeeded,
    only the delivery didn't).
    """
    target = job.delivery_target or "log"
    try:
        if target == "log":
            _deliver_log(job, result)
        elif target.startswith("file:"):
            _deliver_file(job, result, target[len("file:"):])
        elif target.startswith("gateway://"):
            _deliver_gateway_stub(job, result, target)
        else:
            logger.warning(
                "cron %s: unknown delivery target %r — falling back to log",
                job.id, target,
            )
            _deliver_log(job, result)
    except Exception as e:
        logger.warning("cron %s: delivery failed: %s", job.id, e)


def _deliver_log(job: "CronJob", result: dict[str, Any]) -> None:
    logger.info("cron %s: %s", job.id, json.dumps(result, default=str))


def _deliver_file(
    job: "CronJob", result: dict[str, Any], path_str: str
) -> None:
    if not path_str:
        logger.warning("cron %s: empty file: path; skipping", job.id)
        return
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_id": job.id,
        "description": job.description,
        **result,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _deliver_gateway_stub(
    job: "CronJob", result: dict[str, Any], target: str
) -> None:
    logger.warning(
        "cron %s: gateway delivery to %s not yet available — "
        "install Phase 10. Falling back to log.",
        job.id, target,
    )
    _deliver_log(job, result)
