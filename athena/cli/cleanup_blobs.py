"""``athena cleanup-blobs`` — sweep unreferenced tool-result blobs (T2-06).

Walks every ``profiles/<name>/sessions/*.jsonl`` under the active
home, collects every tool_result handle and bare ``tool_result:<hash>``
reference; deletes blobs in ``tool_result_storage_path`` that are
both unreferenced AND older than ``--older-than`` days.

Suggested cron entry:

    0 3 * * * athena cleanup-blobs --older-than 30

Existing top-level CLI uses flat subcommands (no nested ``tools``
group), so this lives as ``athena cleanup-blobs`` rather than the
spec's ``athena tools cleanup-blobs``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import CONFIG_DIR, load_config
from ..tools.tool_result_storage import ToolResultStorage


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="athena cleanup-blobs",
        description=(
            "Sweep unreferenced tool-result blobs older than N days. "
            "Blobs referenced by any session JSONL are kept; recent "
            "blobs are also kept regardless of reference status."
        ),
    )
    ap.add_argument(
        "--older-than",
        type=int,
        default=30,
        help="Days threshold (default: 30).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without deleting.",
    )
    ap.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Override athena home (default: ~/.athena).",
    )
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    cfg = load_config()
    storage_path = Path(cfg.tool_result_storage_path).expanduser()
    if not storage_path.is_absolute():
        # Defensive: a relative path lands under home.
        storage_path = (CONFIG_DIR / storage_path).resolve()

    storage = ToolResultStorage(storage_path, session_id="cleanup")

    home = args.home.expanduser().resolve() if args.home else CONFIG_DIR
    # Walk every profile's sessions/.
    session_logs = list((home / "profiles").rglob("*.jsonl"))

    summary = storage.cleanup_unreferenced(
        session_log_paths=session_logs,
        older_than_days=args.older_than,
        dry_run=args.dry_run,
    )

    action = "would remove" if args.dry_run else "removed"
    print(f"{action}: {summary['blobs_removed']} blobs, {summary['bytes_freed']:,} bytes")
    print(f"kept: {summary['blobs_kept']} blobs")
    return 0
