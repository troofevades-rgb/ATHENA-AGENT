"""``athena audit {skill,memory} <since> <until>`` — diff over the audit log (T3-04).

Read-only replay of athena's existing audit log (MutationAuditLog
under ``<profile_dir>/audit/`` + CheckpointAuditLog under
``<profile_dir>/checkpoints/``). Two actions:

  athena audit skill <since> <until> [--json] [--actor]
  athena audit memory <since> <until> [--json] [--actor]

``<since>`` and ``<until>`` accept ISO 8601, relative ago-forms
(``5m``, ``2h``, ``3d``, ``1w``), and the special tokens ``now`` /
``boot`` / ``last-checkpoint`` (see
:mod:`athena.audit.timestamps`).

Why not ``athena skill diff``? That subcommand already exists in
``athena/cli/skill.py`` and diffs a *single named* skill against
its most recent SnapshotStore snapshot. T3-04's diff is
time-bounded and shows *every* event in a window; the two have
incompatible signatures and live under a new parent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..audit.diff import (
    collect_memory_events,
    collect_rollback_markers,
    collect_skill_events,
    render_memory_diff,
    render_memory_diff_json,
    render_skill_diff,
    render_skill_diff_json,
)
from ..audit.timestamps import TimestampParseError, parse_timestamp
from ..config import CONFIG_DIR, load_config, profile_dir


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="athena audit",
        description=(
            "Time-bounded replay of athena's audit log. Two actions: "
            "skill (skill mutations) and memory (memory mutations)."
        ),
    )
    sub = ap.add_subparsers(dest="action", required=True)

    for action, doc in (
        ("skill", "Diff skill mutations between two timestamps."),
        ("memory", "Diff memory mutations between two timestamps."),
    ):
        p = sub.add_parser(action, help=doc)
        p.add_argument(
            "since",
            help="ISO 8601, relative ('1h', '24h', '3d'), or special token "
            "('now', 'boot', 'last-checkpoint').",
        )
        p.add_argument("until", help="Same forms as <since>; usually 'now'.")
        p.add_argument(
            "--json",
            action="store_true",
            dest="json_out",
            help="Machine-readable output.",
        )
        p.add_argument(
            "--actor",
            help="Filter by write_origin (foreground / curator / "
            "background_review / migration / system).",
        )
        p.add_argument(
            "--profile",
            help="Profile name (default: cfg.profile).",
        )
        p.add_argument(
            "--no-rollback-markers",
            action="store_true",
            help="Omit rollback / checkpoint markers from the output.",
        )
        p.add_argument(
            "--content",
            action="store_true",
            help=(
                "Extract before/after file content from the snapshot "
                "tarballs the audit rows point at and emit a unified "
                "diff per event. Opt-in (slower on long histories) "
                "but produces a real text diff."
            ),
        )

    return ap.parse_args(argv)


def _profile_root(args: argparse.Namespace) -> Path:
    cfg = load_config()
    profile = getattr(args, "profile", None) or cfg.profile or "default"
    return profile_dir(profile)


def main(argv: list[str]) -> int:
    args = _parse(argv)

    pdir = _profile_root(args)
    audit_dir = CONFIG_DIR / "audit"
    session_log = None
    cfg_profile = pdir.name
    # Best-effort: try to find the most-recently-touched session log
    # under the profile for boot / session-start resolution.
    sess_dir = pdir / "sessions"
    if sess_dir.exists():
        jsonls = sorted(
            sess_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if jsonls:
            session_log = jsonls[0]

    try:
        since = parse_timestamp(
            args.since,
            session_log_path=session_log,
            profile_dir=pdir,
        )
        until = parse_timestamp(
            args.until,
            session_log_path=session_log,
            profile_dir=pdir,
        )
    except TimestampParseError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2

    if since >= until:
        sys.stderr.write(
            f"error: 'since' ({since.isoformat()}Z) must be before 'until' ({until.isoformat()}Z)\n"
        )
        return 2

    rollbacks = None
    if not args.no_rollback_markers:
        rollbacks = collect_rollback_markers(profile_dir=pdir, since=since, until=until)

    if args.action == "skill":
        skill_events = collect_skill_events(
            audit_dir=audit_dir,
            since=since,
            until=until,
            actor=args.actor,
            with_content=args.content,
        )
        if args.json_out:
            sys.stdout.write(
                render_skill_diff_json(skill_events, since=since, until=until, rollbacks=rollbacks)
                + "\n"
            )
        else:
            sys.stdout.write(
                render_skill_diff(skill_events, since=since, until=until, rollbacks=rollbacks)
            )
        return 0

    if args.action == "memory":
        memory_events = collect_memory_events(
            audit_dir=audit_dir,
            since=since,
            until=until,
            actor=args.actor,
            with_content=args.content,
        )
        if args.json_out:
            sys.stdout.write(
                render_memory_diff_json(
                    memory_events, since=since, until=until, rollbacks=rollbacks
                )
                + "\n"
            )
        else:
            sys.stdout.write(
                render_memory_diff(memory_events, since=since, until=until, rollbacks=rollbacks)
            )
        return 0

    sys.stderr.write(f"unknown action: {args.action}\n")
    return 2
