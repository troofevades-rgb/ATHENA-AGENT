"""``ocode reindex`` — rebuild the session FTS5 index from JSONL files."""
from __future__ import annotations

import argparse
from pathlib import Path

from ..config import CONFIG_DIR
from ..sessions.reindex import reindex


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="ocode reindex",
        description="Drop and rebuild the session SQLite FTS5 index from JSONL files.",
    )
    ap.add_argument("--profile", default="default", help="Profile to reindex (default: default).")
    ap.add_argument("--home", type=Path, default=None,
                    help="Override ocode home (default: ~/.ocode).")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    home = args.home.expanduser().resolve() if args.home else CONFIG_DIR
    profile_dir = home / "profiles" / args.profile
    if not profile_dir.exists():
        print(f"error: profile dir does not exist: {profile_dir}")
        return 2

    print(f"reindexing {profile_dir} ...")
    summary = reindex(profile_dir)
    print(
        f"done: {summary['sessions']} session(s), {summary['turns']} turn(s) "
        f"indexed in {summary['duration_s']:.2f}s"
    )
    if summary["skipped_files"]:
        print("skipped:")
        for p in summary["skipped_files"]:
            print(f"  • {p}")
    return 0
