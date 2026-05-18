"""``athena profile {list, show, create, switch, delete, rename}``.

Operator surface for profile management. None of these subcommands
construct an Agent — they manipulate the on-disk profile layout
directly, so they're cheap and don't need a model running.

``list`` highlights the active profile with a leading ``*``.
``show`` prints details (path, contents summary). ``create``,
``switch``, ``delete``, and ``rename`` map 1:1 to
:mod:`athena.profiles.manager` functions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..profiles import manager
from ..profiles.resolution import (
    ACTIVE_PROFILE_FILE,
    DEFAULT_PROFILE,
    is_valid_profile_name,
    profile_dir,
    profile_exists,
    resolve_active_profile,
)


# ---- list -----------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    profiles = manager.list_profiles()
    active = resolve_active_profile()
    if args.json:
        sys.stdout.write(json.dumps({
            "active": active,
            "profiles": profiles,
        }, indent=2) + "\n")
        return 0
    if not profiles:
        sys.stdout.write(
            "(no profiles configured — `athena profile create <name>`)\n"
        )
        return 0
    for name in profiles:
        marker = "*" if name == active else " "
        sys.stdout.write(f"{marker} {name}\n")
    return 0


# ---- show -----------------------------------------------------------


def cmd_show(args: argparse.Namespace) -> int:
    name = args.name or resolve_active_profile()
    if not is_valid_profile_name(name):
        sys.stderr.write(f"error: invalid profile name: {name!r}\n")
        return 2
    if not profile_exists(name):
        sys.stderr.write(f"error: profile not found: {name}\n")
        return 2
    root = profile_dir(name)
    summary = _summarize(root)
    if args.json:
        sys.stdout.write(json.dumps({
            "name": name, "path": str(root), **summary,
        }, indent=2) + "\n")
        return 0
    sys.stdout.write(f"{name}\n  path: {root}\n")
    sys.stdout.write(f"  skills:   {summary['skills_count']}\n")
    sys.stdout.write(f"  sessions: {summary['sessions_count']}\n")
    sys.stdout.write(f"  memory:   {summary['memory_count']}\n")
    config_status = "present" if summary["has_config_toml"] else "missing"
    sys.stdout.write(f"  config.toml: {config_status}\n")
    goal = summary.get("goal")
    if goal:
        sys.stdout.write(f"  goal: {goal}\n")
    return 0


def _summarize(root: Path) -> dict[str, Any]:
    """Count user-visible content under a profile dir.

    Cheap counts — no recursive walks. The goal is a one-line snapshot
    for ``athena profile show``, not an audit.
    """
    skills_count = _count_dir_entries(root / "skills")
    sessions_count = _count_dir_entries(
        root / "sessions", pattern="*.meta.json",
    )
    memory_count = _count_dir_entries(root / "memory", pattern="*.md")
    goal_path = root / "goal.txt"
    goal = None
    if goal_path.exists():
        try:
            goal = goal_path.read_text(encoding="utf-8").strip()[:80]
        except OSError:
            pass
    return {
        "skills_count": skills_count,
        "sessions_count": sessions_count,
        "memory_count": memory_count,
        "has_config_toml": (root / "config.toml").exists(),
        "goal": goal,
    }


def _count_dir_entries(path: Path, *, pattern: str | None = None) -> int:
    if not path.exists():
        return 0
    try:
        if pattern:
            return sum(1 for _ in path.glob(pattern))
        return sum(1 for _ in path.iterdir() if not _.name.startswith("."))
    except OSError:
        return 0


# ---- create ---------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    try:
        path = manager.create_profile(args.name, copy_from=args.copy_from)
    except FileExistsError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    except FileNotFoundError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    sys.stdout.write(f"created profile {args.name!r} at {path}\n")
    if args.copy_from:
        sys.stdout.write(f"  cloned from: {args.copy_from}\n")
    return 0


# ---- switch ---------------------------------------------------------


def cmd_switch(args: argparse.Namespace) -> int:
    try:
        manager.switch_profile(args.name)
    except FileNotFoundError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    sys.stdout.write(f"active profile is now {args.name!r}\n")
    return 0


# ---- delete ---------------------------------------------------------


def cmd_delete(args: argparse.Namespace) -> int:
    try:
        manager.delete_profile(args.name, confirm_token=args.confirm)
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    sys.stdout.write(f"deleted profile {args.name!r}\n")
    return 0


# ---- rename ---------------------------------------------------------


def cmd_rename(args: argparse.Namespace) -> int:
    try:
        manager.rename_profile(args.old, args.new)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    sys.stdout.write(f"renamed {args.old!r} → {args.new!r}\n")
    return 0


# ---- argument parser -----------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena profile")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser(
        "list", help="List every profile; active marked with *.",
    )
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(handler=cmd_list)

    p_show = sub.add_parser(
        "show", help="Show details for a profile (defaults to active).",
    )
    p_show.add_argument(
        "name", nargs="?", default=None,
        help="profile name (default: active)",
    )
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(handler=cmd_show)

    p_create = sub.add_parser(
        "create", help="Create a new profile.",
    )
    p_create.add_argument("name", help="new profile name")
    p_create.add_argument(
        "--copy-from", help="clone an existing profile's contents",
    )
    p_create.set_defaults(handler=cmd_create)

    p_switch = sub.add_parser(
        "switch", help="Mark a profile as active for subsequent invocations.",
    )
    p_switch.add_argument("name")
    p_switch.set_defaults(handler=cmd_switch)

    p_delete = sub.add_parser(
        "delete",
        help="Delete a profile (token must equal the name; default is protected).",
    )
    p_delete.add_argument("name")
    p_delete.add_argument(
        "confirm", help="must equal the profile name (anti-typo)",
    )
    p_delete.set_defaults(handler=cmd_delete)

    p_rename = sub.add_parser(
        "rename", help="Rename a profile; updates active_profile if it pointed at old.",
    )
    p_rename.add_argument("old")
    p_rename.add_argument("new")
    p_rename.set_defaults(handler=cmd_rename)

    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
