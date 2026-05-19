"""Cron output delivery routing.

Three delivery targets parsed from ``CronJob.delivery_target``:

- ``log`` — INFO log via the cron logger. Goes wherever stdlib logging
  goes (stderr by default; gateway daemon installs a file handler).
- ``file:<path>`` — append an ISO-timestamped JSON line to ``<path>``.
  Parent dirs are created. Existing content is preserved.
- ``gateway://<platform>/<chat_id>`` — Phase 10 gateway integration.
  Delivers the cron output as a chat message via the running gateway
  daemon's adapter for ``<platform>``. Requires the gateway to be
  running in the same process (typically: cron jobs scheduled inside
  ``athena gateway run``). Falls back to log when no gateway is
  available.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .jobs import CronJob


logger = logging.getLogger("athena.cron")


def deliver(job: CronJob, result: dict[str, Any]) -> None:
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
            _deliver_file(job, result, target[len("file:") :])
        elif target.startswith("gateway://"):
            _deliver_gateway(job, result, target)
        else:
            logger.warning(
                "cron %s: unknown delivery target %r — falling back to log",
                job.id,
                target,
            )
            _deliver_log(job, result)
    except Exception as e:
        logger.warning("cron %s: delivery failed: %s", job.id, e)


def _deliver_log(job: CronJob, result: dict[str, Any]) -> None:
    logger.info("cron %s: %s", job.id, json.dumps(result, default=str))


def _deliver_file(job: CronJob, result: dict[str, Any], path_str: str) -> None:
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


_GATEWAY_PREFIX = "gateway://"


def _parse_gateway_target(target: str) -> tuple[str, str] | None:
    """Parse ``gateway://<platform>/<chat_id>`` into ``(platform, chat_id)``.

    Returns ``None`` on malformed input so the caller can warn and
    fall through.
    """
    if not target.startswith(_GATEWAY_PREFIX):
        return None
    rest = target[len(_GATEWAY_PREFIX) :]
    if "/" not in rest:
        return None
    platform, chat_id = rest.split("/", 1)
    if not platform or not chat_id:
        return None
    return platform, chat_id


def _deliver_gateway(
    job: CronJob,
    result: dict[str, Any],
    target: str,
) -> None:
    """Dispatch the cron result through the running gateway daemon's
    adapter for the named platform.

    Lookup order:

    1. Parse ``gateway://<platform>/<chat_id>`` — malformed → warn + log.
    2. Find a registered :class:`GatewayDaemon` (via
       :mod:`athena.gateway.registry`) — none → warn + log.
    3. Find the adapter for ``platform`` on that daemon — none → warn + log.
    4. Submit ``adapter.send_text(chat_id, body)`` onto the daemon's
       event loop. This is the cross-thread bridge: cron jobs run on
       APScheduler's executor thread (sync), while the adapter's
       ``send_text`` is async. ``run_coroutine_threadsafe`` does the
       trip, bounded by a 10s wait so a wedged adapter doesn't stall
       the cron worker.
    """
    parsed = _parse_gateway_target(target)
    if parsed is None:
        logger.warning(
            "cron %s: malformed gateway target %r — falling back to log",
            job.id,
            target,
        )
        _deliver_log(job, result)
        return
    platform, chat_id = parsed

    # Defer the import so cron's import path doesn't pull gateway.
    from ..gateway import registry as gw_registry

    profile = getattr(job, "profile", None) or "default"
    daemon = gw_registry.get(profile)
    if daemon is None:
        logger.warning(
            "cron %s: no running gateway for profile %r — "
            "falling back to log. Schedule the job inside "
            "`athena gateway run` for gateway delivery.",
            job.id,
            profile,
        )
        _deliver_log(job, result)
        return

    adapter = daemon.adapter_for(platform)
    if adapter is None:
        logger.warning(
            "cron %s: gateway has no %r adapter registered — falling back to log",
            job.id,
            platform,
        )
        _deliver_log(job, result)
        return

    body = _format_cron_body(job, result)
    loop = daemon.approvals._loop
    if loop is None or not loop.is_running():
        logger.warning(
            "cron %s: gateway loop not running — falling back to log",
            job.id,
        )
        _deliver_log(job, result)
        return

    cf = asyncio.run_coroutine_threadsafe(
        adapter.send_text(chat_id, body),
        loop,
    )
    try:
        cf.result(timeout=10.0)
    except Exception as e:
        logger.warning(
            "cron %s: gateway send failed (%s) — falling back to log",
            job.id,
            e,
        )
        _deliver_log(job, result)


def _format_cron_body(job: CronJob, result: dict[str, Any]) -> str:
    """Render the cron result for a chat message.

    Keep it terse — chats are not log files. Includes the job
    description (when set), a status hint, and either the
    ``output`` or ``error`` field if present.
    """
    head = job.description or f"cron {job.id}"
    lines = [f"*{head}*"]
    status = result.get("status")
    if status:
        lines.append(f"_status: {status}_")
    if "output" in result and result["output"]:
        body = str(result["output"]).strip()
        if len(body) > 1500:
            body = body[:1500] + "…"
        lines.append("")
        lines.append(body)
    if "error" in result and result["error"]:
        err = str(result["error"]).strip()
        if len(err) > 500:
            err = err[:500] + "…"
        lines.append("")
        lines.append(f"error: {err}")
    return "\n".join(lines)
