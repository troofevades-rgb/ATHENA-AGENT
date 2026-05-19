"""Curator orchestrator: gates, fork spawn, YAML parse, state update.

``maybe_run_curator`` is the single entry point. It honors paused state,
the interval gate, and the idle gate; otherwise it spawns a fork with
``write_origin="curator"`` and parses the structured YAML output. A
failed parse rejects the run without updating ``last_run_at`` so the
next session retries cleanly.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import CONFIG_DIR
from . import prompts, state, yaml_output

if TYPE_CHECKING:
    from ..agent.core import Agent


logger = logging.getLogger(__name__)


def _skills_root_for(agent: Agent) -> Path:
    """Where the curator's .curator_state lives. Skills are user-global, so
    we anchor to CONFIG_DIR rather than the per-profile dir."""
    return CONFIG_DIR / "skills"


def _logs_root_for(agent: Agent) -> Path:
    return CONFIG_DIR / "logs"


def maybe_run_curator(
    agent: Agent,
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

    # Snapshot the skill landscape before the fork so reconciliation
    # (Retrofit #5) can diff against the post-fork state. On a dry-run
    # we skip the snapshot — nothing should change on disk anyway, and
    # paying the iterdir cost twice is wasteful.
    from . import reconciliation

    before_snapshot = None if dry_run else reconciliation.snapshot_skills(agent.workspace)

    # Defer fork import to call time to keep the orchestrator import-light.
    from ..agent.fork import fork

    fork_start = time.monotonic()
    result = fork(
        agent,
        enabled_toolsets=["skills"],
        system_addendum=addendum,
        # Anthropic + most hosted providers reject (or silently
        # respond empty to) requests whose only turn is a system
        # prompt. The curator fork has no parent conversation to
        # inherit, so synthesize an explicit user "begin" turn so
        # the model has something to respond to.
        user_prompt="Begin the curator consolidation pass now. "
        "Use the skill_view tool to inspect each existing "
        "skill, then emit the structured YAML report per "
        "the schema in your system prompt.",
        max_iterations=agent.cfg.curator.max_iterations,
        write_origin="curator",
        auxiliary_client=True,
        quiet=True,
    )
    duration = time.monotonic() - fork_start

    parsed = yaml_output.parse_curator_report(result.final_response)
    if parsed is None:
        # Surface enough context for the operator to diagnose: was the
        # fork itself broken (result.error set), did it run but produce
        # no text (provider/tool failure), or did it produce text but
        # fail the YAML contract (prompt drift / model not following
        # the schema)? Previously this was a single warning that left
        # all three indistinguishable.
        if result.error:
            logger.warning(
                "curator run rejected: fork error: %s",
                result.error,
            )
        elif not result.final_response:
            logger.warning(
                "curator run rejected: fork returned empty response (stderr len=%d, %d tool calls)",
                len(result.stderr or ""),
                len(result.tool_calls),
            )
            if result.stderr:
                logger.warning(
                    "curator fork stderr tail: %s",
                    (result.stderr or "")[-500:],
                )
        else:
            logger.warning(
                "curator run rejected: malformed YAML in response (len=%d, head=%r)",
                len(result.final_response),
                result.final_response[:300],
            )
        return None

    drift = None
    if before_snapshot is not None:
        after_snapshot = reconciliation.snapshot_skills(agent.workspace)
        drift_report = reconciliation.reconcile(
            before_snapshot,
            after_snapshot,
            parsed["runs"],
        )
        drift = drift_report.to_dict()
        if not drift_report.is_clean:
            logger.warning(
                "curator filesystem drift detected: missing=%d, "
                "unexpected_archive=%d, no_op_after_keep=%d",
                len(drift_report.missing_from_fs),
                len(drift_report.unexpected_archive),
                len(drift_report.no_op_after_keep),
            )

    # Reports come from a separate module — keep this orchestrator focused.
    from . import reports

    summary = reports.write_run(
        agent,
        result,
        parsed,
        dry_run=dry_run,
        logs_root=_logs_root_for(agent),
        drift=drift,
    )

    # Persist a one-line human summary + the report path so the next
    # session's ``athena curator status`` (and the CLI status helper)
    # can display "your last curator pass touched N skills" without
    # re-parsing the report. Mirrors Hermes's last_run_summary +
    # last_report_path fields.
    last_summary = _format_one_line_summary(summary)
    state.write_state(
        skills_root,
        state.State(
            last_run_at=now,
            last_run_duration_seconds=duration,
            last_run_summary=last_summary,
            last_run_summary_shown_at=cur_state.last_run_summary_shown_at,
            last_report_path=summary.get("report_path") if isinstance(summary, dict) else None,
            run_count=cur_state.run_count + 1,
            paused=cur_state.paused,
        ),
    )
    return summary


def _format_one_line_summary(summary: Any) -> str | None:
    """Render a one-line digest of a curator run for the status line.

    Accepts the shape :mod:`athena.curator.reports` writes. Returns
    ``None`` rather than raising if the shape is unexpected — we never
    want a status-line render to crash the next session start.

    Output examples:
        "12 kept, 3 absorbed, 1 pruned"
        "5 decision(s)"

    Buckets the wide enum into three families so the line stays
    readable:
      - kept       → KEEP_AS_IS
      - absorbed   → CONSOLIDATE_INTO + CREATE_UMBRELLA + DEMOTE_TO_*
      - pruned     → PRUNE
    """
    if not isinstance(summary, dict):
        return None
    counts = summary.get("decision_counts")
    if isinstance(counts, dict):
        kept = counts.get("KEEP_AS_IS", 0)
        pruned = counts.get("PRUNE", 0)
        absorbed = (
            counts.get("CONSOLIDATE_INTO", 0)
            + counts.get("CREATE_UMBRELLA", 0)
            + counts.get("DEMOTE_TO_REFERENCES", 0)
            + counts.get("DEMOTE_TO_TEMPLATES", 0)
            + counts.get("DEMOTE_TO_SCRIPTS", 0)
        )
        parts: list[str] = []
        if kept:
            parts.append(f"{kept} kept")
        if absorbed:
            parts.append(f"{absorbed} absorbed")
        if pruned:
            parts.append(f"{pruned} pruned")
        if parts:
            return ", ".join(parts)
    runs = summary.get("decisions") or summary.get("runs")
    if isinstance(runs, list):
        return f"{len(runs)} decision(s)"
    return None
