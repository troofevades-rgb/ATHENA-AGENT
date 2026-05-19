"""``athena memory {diff, rollback}`` — operate on a single memory entry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import load_config
from ..memory.providers.builtin_file import BuiltinFileProvider
from ..profiles.resolution import resolve_active_profile
from .rollback import (
    RollbackError,
    confirm_via_stdio,
    diff_target,
    rollback_target,
)


def _resolve_memory_file(name: str, profile: str) -> Path | None:
    """Find the on-disk file backing memory entry ``name``."""
    provider = BuiltinFileProvider()
    entry = provider.read_entry(profile, name)
    if entry is None:
        return None
    return entry.path


def _active_profile(arg: str | None) -> str:
    cfg = load_config()
    return resolve_active_profile(cli_arg=arg, config_default=cfg.profile)


def cmd_diff(args: argparse.Namespace) -> int:
    profile = _active_profile(args.profile)
    target = _resolve_memory_file(args.name, profile)
    if target is None:
        sys.stderr.write(f"error: no memory entry named {args.name!r} under profile {profile!r}\n")
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
    profile = _active_profile(args.profile)
    target = _resolve_memory_file(args.name, profile)
    if target is None:
        sys.stderr.write(f"error: no memory entry named {args.name!r} under profile {profile!r}\n")
        return 1
    confirm = (lambda _: True) if args.yes else confirm_via_stdio
    try:
        result = rollback_target(
            target,
            tool_name="memory_rollback",
            snapshot_id=args.to,
            confirm=confirm,
        )
    except RollbackError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    sys.stdout.write(f"{result['status']}: snapshot {result['snapshot_id']}\n")
    return 0 if result["status"] == "restored" else 1


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena memory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_diff = sub.add_parser("diff", help="Diff a memory entry against its most recent snapshot.")
    p_diff.add_argument("name")
    p_diff.add_argument("--to", help="Specific snapshot_id.")
    p_diff.add_argument("--profile")
    p_diff.set_defaults(handler=cmd_diff)

    p_rb = sub.add_parser("rollback", help="Roll a memory entry back to a snapshot.")
    p_rb.add_argument("name")
    p_rb.add_argument("--to")
    p_rb.add_argument("-y", "--yes", action="store_true")
    p_rb.add_argument("--profile")
    p_rb.set_defaults(handler=cmd_rollback)
    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
