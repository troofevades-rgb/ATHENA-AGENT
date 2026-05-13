"""Curator orchestrator: gates, fork spawn, YAML parse, state update.

``maybe_run_curator`` is the single entry point. It honors paused state,
the interval gate, and the idle gate; otherwise it spawns a fork with
``write_origin="curator"`` and parses the structured YAML output. A
failed parse rejects the run without updating ``last_run_at`` so the
next session retries cleanly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import CONFIG_DIR
from . import prompts, state, yaml_output

if TYPE_CHECKING:
    from ..agent.core import Agent


logger = logging.getLogger(__name__)


def _skills_root_for(agent: "Agent") -> Path:
    """Where the curator's .curator_state lives. Skills are user-global, so
    we anchor to CONFIG_DIR rather than the per-profile dir."""
    return CONFIG_DIR / "skills"


def _logs_root_for(agent: "Agent") -> Path:
    return CONFIG_DIR / "logs"


def maybe_run_curator(
    agent: "Agent",
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict | None:
    """Run the curator if its gates pass; return a summary dict, else None.

    Gates (all bypassed when ``force=True``):

    - paused state — the user explicitly stopped the curator
    - interval — at least ``cfg.curator.interval_hours`` since last run
    - idle — no other session ended within ``cfg.curator.min_idle_hours``
    """
    skills_root = _skills_root_for(agent)
    cur_state = state.read_state(skills_root)
    if cur_state.paused and not force:
        return None

    now = datetime.now(timezone.utc)
    interval = timedelta(hours=agent.cfg.curator.interval_hours)
    idle = timedelta(hours=agent.cfg.curator.min_idle_hours)

    if not force:
        if cur_state.last_run_at and (now - cur_state.last_run_at) < interval:
            return None
        last_other = (
            agent.session_store.most_recent_other_session(exclude=agent.session_id)
            if agent.session_store is not None
            else None
        )
        if (
            last_other is not None
            and last_other.ended_at is not None
            and (now - last_other.ended_at) < idle
        ):
            return None

    addendum = prompts.CURATOR_REVIEW_PROMPT
    if dry_run:
        addendum = prompts.DRY_RUN_BANNER + addendum

    # Defer fork import to call time to keep the orchestrator import-light.
    from ..agent.fork import fork
    result = fork(
        agent,
        enabled_toolsets=["skills"],
        system_addendum=addendum,
        max_iterations=agent.cfg.curator.max_iterations,
        write_origin="curator",
        auxiliary_client=True,
        quiet=True,
    )

    parsed = yaml_output.parse_curator_report(result.final_response)
    if parsed is None:
        logger.warning("curator run rejected: missing or malformed YAML output")
        return None

    # Reports come from a separate module — keep this orchestrator focused.
    from . import reports
    summary = reports.write_run(
        agent,
        result,
        parsed,
        dry_run=dry_run,
        logs_root=_logs_root_for(agent),
    )

    state.write_state(skills_root, state.State(
        last_run_at=now,
        run_count=cur_state.run_count + 1,
        paused=cur_state.paused,
    ))
    return summary
