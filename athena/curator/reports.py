"""Persist a curator run as run.json + REPORT.md.

Each run lands under ``<logs_root>/curator/<YYYYMMDD-HHMMSS>/``:

- ``run.json`` carries the structured parsed YAML, fork metadata
  (duration, stdout/stderr byte counts, error), and the dry-run flag —
  machine readable, used by ``athena curator inspect-last`` and Phase 16
  telemetry.
- ``REPORT.md`` is a human-readable summary printed at the end of a
  foreground ``athena curator run``.

The function returns the same shape the orchestrator hands back to
``maybe_run_curator`` callers.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_run(
    agent: Any,
    fork_result: Any,
    parsed_yaml: dict[str, Any],
    *,
    dry_run: bool = False,
    logs_root: Path | None = None,
    drift: dict[str, Any] | None = None,
    usage_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write run.json + REPORT.md and return the run summary dict.

    ``drift`` is the dict from
    :meth:`athena.curator.reconciliation.DriftReport.to_dict` — surfaces
    discrepancies between what the YAML claimed and what's actually on
    disk. Pass ``None`` (the dry-run default) to skip drift reporting.
    """
    runs = parsed_yaml.get("runs") or []
    now = datetime.now(timezone.utc)
    run_dir = (logs_root or Path.cwd()) / "curator" / now.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    decision_counts = Counter(r["decision"] for r in runs)
    targets_by_decision: dict[str, list[str]] = {}
    for r in runs:
        if r.get("target"):
            targets_by_decision.setdefault(r["decision"], []).append(r["target"])

    # absorbed_into → list[absorbed_skill_name]. Drives the future
    # skill-reference migration cron: when an old conversation references
    # absorbed_skill_name, the cron rewrites the reference to the umbrella.
    absorptions: dict[str, list[str]] = {}
    for r in runs:
        umbrella = r.get("absorbed_into")
        if isinstance(umbrella, str) and umbrella:
            absorptions.setdefault(umbrella, []).append(r["skill"])

    summary = {
        "started_at": now.isoformat(),
        "dry_run": dry_run,
        "total_skills": len(runs),
        "decision_counts": dict(decision_counts),
        "targets_by_decision": targets_by_decision,
        "absorptions": absorptions,
        "drift": drift or {},
        "decisions": runs,
        "fork": {
            "duration_s": getattr(fork_result, "duration_s", 0.0),
            "error": getattr(fork_result, "error", None),
            "child_session_id": getattr(fork_result, "child_session_id", None),
            "stdout_bytes": len(getattr(fork_result, "stdout", "") or ""),
            "stderr_bytes": len(getattr(fork_result, "stderr", "") or ""),
        },
        "report_path": str(run_dir / "REPORT.md"),
    }
    if usage_metrics is not None:
        # T3-06R: per-skill usage signal collected alongside the
        # curator's decisions. Shape: {"top": [...], "never_used":
        # [...], "stale_30": [...]}, each entry a dict with name +
        # views + last_used_at.
        summary["usage"] = usage_metrics

    (run_dir / "run.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (run_dir / "REPORT.md").write_text(_render_markdown(summary), encoding="utf-8")
    if getattr(fork_result, "stdout", None):
        (run_dir / "fork-stdout.log").write_text(fork_result.stdout, encoding="utf-8")
    if getattr(fork_result, "stderr", None):
        (run_dir / "fork-stderr.log").write_text(fork_result.stderr, encoding="utf-8")

    return summary


def _render_markdown(summary: dict[str, Any]) -> str:
    started = summary["started_at"]
    suffix = " (dry-run)" if summary["dry_run"] else ""
    lines: list[str] = [f"# Curator run {started}{suffix}", ""]
    lines.append(f"Total skills reviewed: {summary['total_skills']}")
    lines.append(f"Fork duration: {summary['fork']['duration_s']:.2f}s")
    if summary["fork"]["error"]:
        lines.append(f"Fork error: {summary['fork']['error']}")
    lines.append("")
    lines.append("## Decisions")
    if not summary["decision_counts"]:
        lines.append("(none)")
    else:
        for decision, count in sorted(summary["decision_counts"].items()):
            targets = summary["targets_by_decision"].get(decision)
            if targets:
                lines.append(f"  - {decision}: {count} ({', '.join(sorted(set(targets)))})")
            else:
                lines.append(f"  - {decision}: {count}")
    lines.append("")
    lines.append("## Per-skill decisions")
    if not summary["decisions"]:
        lines.append("(none)")
    else:
        for r in summary["decisions"]:
            target_suffix = f" → {r['target']}" if r.get("target") else ""
            lines.append(f"- **{r['skill']}**: {r['decision']}{target_suffix}")
            if r.get("rationale"):
                lines.append(f"    rationale: {r['rationale']}")

    absorptions = summary.get("absorptions") or {}
    if absorptions:
        lines.append("")
        lines.append("## Absorptions (for reference migration)")
        for umbrella, absorbed in sorted(absorptions.items()):
            for name in sorted(absorbed):
                lines.append(f"- `{name}` → `{umbrella}`")

    usage = summary.get("usage") or {}
    if usage:
        lines.append("")
        lines.append("## Per-skill usage (T3-06R)")
        lines.append(
            "Usage signal informs the decisions above; it does not override the hard rules."
        )
        top = usage.get("top") or []
        never = usage.get("never_used") or []
        stale_30 = usage.get("stale_30") or []
        if top:
            lines.append("")
            lines.append("### Most-viewed")
            for row in top:
                lines.append(
                    f"- `{row.get('name')}`: {row.get('views', 0)} views, "
                    f"last used {row.get('last_used_at') or 'never'}"
                )
        if never:
            lines.append("")
            lines.append(f"### Never viewed ({len(never)})")
            for n in never:
                lines.append(f"- `{n}`")
        if stale_30:
            lines.append("")
            lines.append(f"### Stale > 30 days ({len(stale_30)})")
            for row in stale_30:
                lines.append(f"- `{row.get('name')}` (last used {row.get('last_used_at')})")

    drift = summary.get("drift") or {}
    if any(drift.values()):
        lines.append("")
        lines.append("## ⚠ Filesystem drift")
        if drift.get("missing_from_fs"):
            lines.append("")
            lines.append("### Claimed removal but still active on disk")
            for d in drift["missing_from_fs"]:
                lines.append(
                    f"- `{d['skill']}` (claimed {d['decision']}, "
                    f"observed state: {d['observed_state']})"
                )
        if drift.get("unexpected_archive"):
            lines.append("")
            lines.append("### Archived on disk but not in YAML output")
            for d in drift["unexpected_archive"]:
                lines.append(f"- `{d['skill']}` ({d['before_state']} → {d['after_state']})")
        if drift.get("no_op_after_keep"):
            lines.append("")
            lines.append("### KEEP_AS_IS but state flipped")
            for d in drift["no_op_after_keep"]:
                lines.append(f"- `{d['skill']}` ({d['before_state']} → {d['after_state']})")
    return "\n".join(lines).rstrip() + "\n"
