"""``athena skill {diff, rollback}`` — operate on a single skill."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..skills.discovery import discover_skills
from .rollback import (
    RollbackError,
    confirm_via_stdio,
    diff_target,
    rollback_target,
)


def _resolve_skill_md(name: str, workspace: Path | None) -> Path | None:
    skills = discover_skills(workspace, include_archived=False)
    entry = skills.get(name)
    if entry is None:
        return None
    _, skill_dir = entry
    return skill_dir / "SKILL.md"


def cmd_diff(args: argparse.Namespace) -> int:
    workspace = Path(args.cwd).resolve() if args.cwd else None
    target = _resolve_skill_md(args.name, workspace)
    if target is None:
        sys.stderr.write(f"error: no skill named {args.name!r}\n")
        return 1
    try:
        diff = diff_target(target, snapshot_id=args.to)
    except RollbackError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    if not diff.strip():
        sys.stdout.write("(no differences)\n")
        return 0
    sys.stdout.write(diff)
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    workspace = Path(args.cwd).resolve() if args.cwd else None
    target = _resolve_skill_md(args.name, workspace)
    if target is None:
        sys.stderr.write(f"error: no skill named {args.name!r}\n")
        return 1
    confirm = (lambda _: True) if args.yes else confirm_via_stdio
    try:
        result = rollback_target(
            target,
            tool_name="skill_rollback",
            snapshot_id=args.to,
            confirm=confirm,
        )
    except RollbackError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    sys.stdout.write(f"{result['status']}: snapshot {result['snapshot_id']}\n")
    return 0 if result["status"] == "restored" else 1


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena skill")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_diff = sub.add_parser("diff", help="Diff a skill against its most recent snapshot.")
    p_diff.add_argument("name")
    p_diff.add_argument("--to", help="Specific snapshot_id.")
    p_diff.add_argument("-C", "--cwd", help="Workspace directory.")
    p_diff.set_defaults(handler=cmd_diff)

    p_rb = sub.add_parser("rollback", help="Roll a skill back to a snapshot.")
    p_rb.add_argument("name")
    p_rb.add_argument("--to", help="Specific snapshot_id.")
    p_rb.add_argument("-y", "--yes", action="store_true", help="Skip confirm prompt.")
    p_rb.add_argument("-C", "--cwd", help="Workspace directory.")
    p_rb.set_defaults(handler=cmd_rollback)
    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
