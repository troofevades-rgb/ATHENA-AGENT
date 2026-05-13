"""Apply the deterministic lifecycle state machine at session start.

Phase 1's :mod:`ocode.skills.state_machine` exposes the pure-function
``apply_transitions``. This module is the small glue that calls it once
per session start, surfaces a summary, and never raises into the agent
init path — a failed lifecycle pass is a warning, not a fatal error.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from . import state_machine

logger = logging.getLogger(__name__)


def run_lifecycle(
    workspace: Path | None = None,
    *,
    now: datetime | None = None,
    stale_after_days: int = 30,
    archive_after_days: int = 90,
) -> dict[str, list[str]]:
    """Run the lifecycle state machine for one session start.

    Returns the action dict from ``apply_transitions``. Logs an INFO line
    summarizing what happened when anything actually moved.
    """
    try:
        actions = state_machine.apply_transitions(
            workspace,
            now=now,
            stale_after_days=stale_after_days,
            archive_after_days=archive_after_days,
        )
    except Exception as e:
        logger.warning("lifecycle pass failed (continuing): %s", e)
        return {"marked_stale": [], "archived": [], "reactivated": []}

    total = sum(len(v) for v in actions.values())
    if total:
        logger.info(
            "lifecycle: %d stale, %d archived, %d reactivated",
            len(actions["marked_stale"]),
            len(actions["archived"]),
            len(actions["reactivated"]),
        )
    return actions
