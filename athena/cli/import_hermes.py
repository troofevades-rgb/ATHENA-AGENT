"""``athena import-from-hermes`` — one-shot migration of Hermes data into athena v2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..migration.hermes_import import DEFAULT_DOMAINS, run_import

SUPPORTED_HERMES_VERSIONS = ("0.x", "1.0", "1.1")  # advisory only


def _detect_hermes_home(source: Path) -> bool:
    return (source / "config.yaml").exists() or (source / "skills").exists()


def _read_hermes_version(source: Path) -> str | None:
    cfg = source / "config.yaml"
    if not cfg.exists():
        return None
    try:
        import yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data.get("hermes_version") or data.get("version")


def _summarize_intent(source: Path, active: list[str]) -> str:
    parts: list[str] = []
    if "skills" in active:
        skills = source / "skills"
        count = (
            sum(1 for p in skills.iterdir() if p.is_dir() and not p.name.startswith("."))
            if skills.exists()
            else 0
        )
        archived = (
            sum(1 for p in (skills / ".archive").iterdir() if p.is_dir())
            if (skills / ".archive").exists()
            else 0
        )
        parts.append(f"  • skills: {count} active + {archived} archived")
    if "memory" in active:
        db = source / "memory.db"
        parts.append(f"  • memory: {'memory.db detected' if db.exists() else '(no memory.db)'}")
    if "sessions" in active:
        sd = source / "sessions"
        count = sum(1 for _ in sd.glob("*.jsonl")) if sd.exists() else 0
        parts.append(f"  • sessions: {count} jsonl files")
    if "config" in active:
        parts.append(
            f"  • config: {'config.yaml detected' if (source / 'config.yaml').exists() else '(no config.yaml)'}"
        )
    if "mcp" in active:
        parts.append(
            f"  • mcp: {'mcp.json detected' if (source / 'mcp.json').exists() else '(no mcp.json)'}"
        )
    return "\n".join(parts)


POST_IMPORT_CHECKLIST = """\
Post-import checklist
---------------------
  1. Inspect REPORT.md for warnings (especially WARNING entries).
  2. Try `athena skill list` to confirm imported skills appear.
  3. Run `athena` interactively; the migrated profile is loaded by default.
  4. Review credentials.json (if present) and move secrets to your password
     manager / keyring as desired.
  5. Migration-origin skills are write-protected from the curator until you
     touch them — make any final edits with `skill_manage patch` to opt in.
"""


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="athena import-from-hermes",
        description="Migrate Hermes Agent data into athena v2.",
    )
    ap.add_argument(
        "--source", required=True, type=Path, help="Hermes home directory (e.g. ~/.hermes)"
    )
    ap.add_argument(
        "--dest",
        required=True,
        type=Path,
        help="athena home directory to write into (e.g. ~/.athena)",
    )
    ap.add_argument("--profile", default="default")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--include",
        help="Comma-separated subset of domains to import (default: all).",
    )
    ap.add_argument(
        "--exclude",
        help="Comma-separated subset of domains to skip.",
    )
    ap.add_argument("--no-confirm", action="store_true")
    return ap.parse_args(argv)


def _split(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {p.strip() for p in value.split(",") if p.strip()}


def main(argv: list[str]) -> int:
    args = _parse(argv)
    source = args.source.expanduser().resolve()
    dest = args.dest.expanduser().resolve()

    if not source.exists():
        print(f"error: source does not exist: {source}", file=sys.stderr)
        return 2
    if not _detect_hermes_home(source):
        print(
            f"error: source does not look like a Hermes home (no config.yaml or skills/): {source}",
            file=sys.stderr,
        )
        return 2

    version = _read_hermes_version(source)
    if version is None:
        print(f"warning: could not detect Hermes version at {source}", file=sys.stderr)
    elif not any(version.startswith(v.rstrip("x")) for v in SUPPORTED_HERMES_VERSIONS):
        print(
            f"warning: Hermes version {version!r} is outside the supported matrix "
            f"{SUPPORTED_HERMES_VERSIONS}; proceeding anyway",
            file=sys.stderr,
        )

    include = _split(args.include) or set(DEFAULT_DOMAINS)
    exclude = _split(args.exclude) or set()
    active = sorted(include - exclude)

    print(f"Migrating Hermes data from {source} → {dest} (profile={args.profile})")
    if args.dry_run:
        print("(dry run — no files will be written)")
    print("Planned domains:")
    print(_summarize_intent(source, active))

    if not args.no_confirm and not args.dry_run:
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("aborted")
            return 1

    report_dir = run_import(
        source,
        dest,
        profile=args.profile,
        include=include,
        exclude=exclude,
        dry_run=args.dry_run,
    )

    print(f"\nDone. Report: {report_dir / 'REPORT.md'}")
    print()
    print(POST_IMPORT_CHECKLIST)
    return 0
