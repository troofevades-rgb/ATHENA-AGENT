"""``athena checkpoint`` — non-interactive checkpoint operations (T3-03.8).

Three actions on the same subcommand surface:

  athena checkpoint create [--label LABEL] [--session SESSION_ID]
  athena checkpoint list [--session SESSION_ID]
  athena checkpoint rollback <label-or-id> [--session SESSION_ID]
  athena checkpoint purge [--session SESSION_ID]

A bare ``athena checkpoint`` (no action verb) defaults to ``create``
to match the simpler spec form ``athena checkpoint --label ...``.

``--session`` defaults to the most recent session in the active
profile.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

from ..agent.checkpoints import (
    CheckpointAuditLog,
    CheckpointManager,
    CheckpointNotFound,
)
from ..config import load_config, profile_dir
from ..safety.snapshots import SnapshotStore


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="athena checkpoint",
        description=("Create, list, rollback to, or purge conversation checkpoints for a session."),
    )
    sub = ap.add_subparsers(dest="action")

    p_create = sub.add_parser("create", help="Create a checkpoint (default).")
    p_create.add_argument("--label", default=None)
    p_create.add_argument("--session", help="Session ID (default: most recent).")
    p_create.add_argument("--profile", help="Profile name (default: cfg.profile).")

    p_list = sub.add_parser("list", help="List checkpoints for a session.")
    p_list.add_argument("--session")
    p_list.add_argument("--profile")

    p_rb = sub.add_parser("rollback", help="Roll back to a checkpoint.")
    p_rb.add_argument("label_or_id", help="Checkpoint label or id.")
    p_rb.add_argument("--session")
    p_rb.add_argument("--profile")
    p_rb.add_argument(
        "--yes",
        action="store_true",
        help="Auto-overwrite on file conflict instead of skipping.",
    )

    p_purge = sub.add_parser("purge", help="Drop auto-created pre-rollback entries.")
    p_purge.add_argument("--session")
    p_purge.add_argument("--profile")

    # Bare-call convenience: `athena checkpoint --label foo` works without
    # naming `create` explicitly.
    ap.add_argument("--label", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--session", help=argparse.SUPPRESS)
    ap.add_argument("--profile", help=argparse.SUPPRESS)

    return ap.parse_args(argv)


def _profile_root(args: argparse.Namespace) -> Path:
    cfg = load_config()
    profile = getattr(args, "profile", None) or cfg.profile or "default"
    return profile_dir(profile)


def _resolve_session(args: argparse.Namespace) -> str:
    """Pick a session id: explicit --session > most recently-modified
    session JSONL under the profile's sessions dir."""
    explicit = getattr(args, "session", None)
    if explicit:
        return cast(str, explicit)
    sessions_dir = _profile_root(args) / "sessions"
    if not sessions_dir.exists():
        raise SystemExit(f"no sessions dir at {sessions_dir}")
    candidates = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"no sessions found under {sessions_dir}")
    return candidates[0].stem


def _build_manager(session_id: str, args: argparse.Namespace) -> CheckpointManager:
    pdir = _profile_root(args)
    ckpt_dir = pdir / "checkpoints" / session_id
    session_log = pdir / "sessions" / f"{session_id}.jsonl"
    return CheckpointManager(
        session_id=session_id,
        session_log_path=session_log,
        checkpoint_dir=ckpt_dir,
        snapshot_store=SnapshotStore(),
        profile_dir=pdir,
        workspace=Path.cwd(),
        audit_log=CheckpointAuditLog(ckpt_dir / "audit.jsonl"),
    )


def main(argv: list[str]) -> int:
    args = _parse(argv)
    action = args.action or "create"
    session_id = _resolve_session(args)
    mgr = _build_manager(session_id, args)

    if action == "create":
        cp = mgr.create(label=args.label)
        sys.stdout.write(f"checkpoint: {cp.id}  (label={cp.label!r}, session={session_id})\n")
        return 0
    if action == "list":
        cps = mgr.list()
        if not cps:
            sys.stdout.write(f"no checkpoints for session {session_id}\n")
            return 0
        for cp in cps:
            note = f"  ({cp.notes})" if cp.notes else ""
            sys.stdout.write(f"  {cp.id}  {cp.created_at}  {cp.label}{note}\n")
        return 0
    if action == "rollback":
        confirm = (lambda _p, _o, _c: "overwrite") if args.yes else None
        try:
            cp = mgr.rollback_to(args.label_or_id, on_file_conflict=confirm)
        except CheckpointNotFound as e:
            sys.stderr.write(f"error: {e}\n")
            return 1
        sys.stdout.write(f"rolled back to {cp.label!r} ({cp.id}). pre-rollback state saved.\n")
        return 0
    if action == "purge":
        n = mgr.purge_pre_rollback()
        sys.stdout.write(f"purged {n} pre-rollback checkpoint(s)\n")
        return 0

    sys.stderr.write(f"unknown action: {action}\n")
    return 2
