"""``athena skill {add, diff, rollback, metrics}`` — operate on a single skill."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import load_config
from ..skills.discovery import discover_skills
from ..skills.importer import ImportResult, import_archive, import_skill
from ..skills.validation import validate_skill
from .rollback import (
    RollbackError,
    confirm_via_stdio,
    diff_target,
    rollback_target,
)


def _import_base(args: argparse.Namespace) -> Path:
    """Pick the install root: user-global by default, workspace if
    --workspace is set."""
    if getattr(args, "workspace", False):
        workspace = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()
        return workspace / ".athena" / "skills"
    return Path.home() / ".athena" / "skills"


def cmd_add(args: argparse.Namespace) -> int:
    """``athena skill add <path>`` — import a SKILL.md, skill dir, or
    archive into the user-global or workspace skills tree."""
    source = Path(args.path).expanduser()
    if not source.exists():
        sys.stderr.write(f"error: {source} does not exist\n")
        return 1
    base = _import_base(args)
    policy = "overwrite" if args.overwrite else "rename" if args.rename else "abort"

    if (
        source.is_file()
        and source.suffix.lower() in (".zip", ".tar", ".tgz")
        or (source.is_file() and "".join(source.suffixes[-2:]).lower().endswith(".tar.gz"))
    ):
        result = import_archive(source, base=base, on_conflict=policy)
    else:
        result = import_skill(source, base=base, on_conflict=policy)

    return _print_import_result(result)


def _print_import_result(result: ImportResult) -> int:
    """Render an :class:`ImportResult` to stdout/stderr and return an
    exit code matching its status (0 on installed/overwritten/renamed,
    nonzero otherwise)."""
    if result.status == "rejected":
        sys.stderr.write("error: import rejected\n")
        for e in result.errors:
            sys.stderr.write(f"  - {e}\n")
        return 1
    if result.status == "skipped":
        sys.stderr.write(
            f"skipped: {result.name!r} already exists at {result.dest}. "
            "Use --overwrite or --rename.\n"
        )
        for w in result.warnings:
            sys.stderr.write(f"  - {w}\n")
        return 2
    verb = {
        "installed": "installed",
        "overwritten": "overwrote existing",
        "renamed": "installed (renamed from collision)",
    }.get(result.status, result.status)
    sys.stdout.write(f"{verb}: {result.name} -> {result.dest}\n")
    for w in result.warnings:
        sys.stderr.write(f"  warning: {w}\n")
    return 0


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


def cmd_metrics(args: argparse.Namespace) -> int:
    """``athena skill metrics`` — top / stale / never-used (T3-06R)."""
    from ..config import profile_dir as _profile_dir
    from ..skills.metrics import SkillMetricsStore, metrics_path

    cfg = load_config()
    profile = args.profile or cfg.profile or "default"
    pdir = _profile_dir(profile)
    store = SkillMetricsStore(metrics_path(pdir))
    workspace = Path(args.cwd).resolve() if args.cwd else None
    catalogue = list(discover_skills(workspace).keys())

    top = store.top(n=max(1, int(args.top)))
    stale = store.stale(older_than_days=max(1, int(args.stale_days)))
    never = store.never_used(catalogue)

    if args.json_out:
        import json as _json

        payload = {
            "profile": profile,
            "top": [m.to_dict() for m in top],
            "stale_days": int(args.stale_days),
            "stale": [m.to_dict() for m in stale],
            "never_used": never,
        }
        sys.stdout.write(_json.dumps(payload, indent=2) + "\n")
        return 0

    sys.stdout.write(f"profile: {profile}\n\n")
    sys.stdout.write(f"top {len(top)} most-viewed skills:\n")
    if not top:
        sys.stdout.write("  (no recorded views yet)\n")
    else:
        for m in top:
            sys.stdout.write(f"  {m.name:30}  {m.views:>5} views  last={m.last_used_at}\n")

    sys.stdout.write(f"\nstale (>{args.stale_days} days since last view):\n")
    if not stale:
        sys.stdout.write("  (none)\n")
    else:
        for m in stale:
            sys.stdout.write(f"  {m.name:30}  {m.views:>5} views  last={m.last_used_at}\n")

    sys.stdout.write(f"\nnever viewed ({len(never)} skill(s) in the catalogue):\n")
    if not never:
        sys.stdout.write("  (none)\n")
    else:
        for n in never:
            sys.stdout.write(f"  {n}\n")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """``athena skill lint <name>|--all`` — run the same frontmatter
    validator the importer uses, but against installed skills, so a
    manual SKILL.md edit gets checked without waiting for the next
    import. Exit 1 if any skill has problems."""
    workspace = Path(args.cwd).resolve() if args.cwd else None
    skills = discover_skills(workspace, include_archived=True)
    if args.all:
        targets = sorted(skills.keys())
    elif args.name:
        if args.name not in skills:
            sys.stderr.write(f"error: no skill named {args.name!r}\n")
            return 1
        targets = [args.name]
    else:
        sys.stderr.write("error: give a skill name or --all\n")
        return 2
    if not targets:
        sys.stdout.write("(no skills found)\n")
        return 0

    problems = 0
    for name in targets:
        _, skill_dir = skills[name]
        errs = validate_skill(skill_dir)
        if errs:
            problems += len(errs)
            sys.stdout.write(f"FAIL  {name}\n")
            for e in errs:
                sys.stdout.write(f"        - {e}\n")
        else:
            sys.stdout.write(f"ok    {name}\n")
    if problems:
        sys.stderr.write(f"\n{problems} problem(s) across {len(targets)} skill(s)\n")
        return 1
    sys.stdout.write(f"\nall {len(targets)} skill(s) valid\n")
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

    p_add = sub.add_parser(
        "add",
        help="Import a SKILL.md, skill dir, or archive (.zip / .tar.gz).",
    )
    p_add.add_argument("path", help="Source path: SKILL.md, skill dir, or archive.")
    p_add.add_argument(
        "--workspace",
        action="store_true",
        help="Install into <cwd>/.athena/skills/ instead of ~/.athena/skills/.",
    )
    p_add.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing skill of the same name.",
    )
    p_add.add_argument(
        "--rename",
        action="store_true",
        help="On name collision, install under <name>-N instead of aborting.",
    )
    p_add.add_argument("-C", "--cwd", help="Workspace directory (with --workspace).")
    p_add.set_defaults(handler=cmd_add)

    p_lint = sub.add_parser(
        "lint",
        help="Validate an installed skill's SKILL.md (catches manual edits without a re-import).",
    )
    p_lint.add_argument("name", nargs="?", help="Skill name to lint (omit with --all).")
    p_lint.add_argument("--all", action="store_true", help="Lint every discovered skill.")
    p_lint.add_argument("-C", "--cwd", help="Workspace directory.")
    p_lint.set_defaults(handler=cmd_lint)

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

    p_metrics = sub.add_parser(
        "metrics",
        help="Show per-skill usage metrics (T3-06R).",
    )
    p_metrics.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top-viewed skills to show (default: 10).",
    )
    p_metrics.add_argument(
        "--stale-days",
        type=int,
        default=30,
        help="Threshold for the stale list (default: 30).",
    )
    p_metrics.add_argument(
        "--profile",
        default=None,
        help="Profile name (default: cfg.profile).",
    )
    p_metrics.add_argument("-C", "--cwd", help="Workspace directory (for never-used join).")
    p_metrics.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Machine-readable output.",
    )
    p_metrics.set_defaults(handler=cmd_metrics)
    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
