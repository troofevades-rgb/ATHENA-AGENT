"""``athena snapshot {list, show, pin, unpin, prune}``.

Browse the content-addressed snapshot store (Phase 17.1). Snapshots
are pre-state tarballs taken before every agent-driven mutation;
this CLI is the user's window into the store for audit and recovery.
"""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
from datetime import datetime
from pathlib import Path

from ..safety.context import get_snapshot_store
from ..safety.snapshots import Snapshot


def _fmt_row(snap: Snapshot) -> str:
    paths = ",".join(p.name for p in snap.paths) or "-"
    pinned = "📌 " if snap.pinned else "   "
    created = snap.created_at.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"{pinned}{created}  {snap.snapshot_id:<48}  "
        f"{snap.write_origin:<18}  {snap.tool_name or '-':<20}  {paths}"
    )


def cmd_list(args: argparse.Namespace) -> int:
    store = get_snapshot_store()
    snaps = store.list_snapshots(
        path_filter=Path(args.path) if args.path else None,
        write_origin_filter=args.write_origin,
        limit=args.limit,
    )
    if not snaps:
        sys.stdout.write("(no snapshots)\n")
        return 0
    if args.json:
        sys.stdout.write(json.dumps([
            {
                "snapshot_id": s.snapshot_id,
                "created_at": s.created_at.isoformat(),
                "write_origin": s.write_origin,
                "tool_name": s.tool_name,
                "paths": [str(p) for p in s.paths],
                "pinned": s.pinned,
            } for s in snaps
        ], indent=2) + "\n")
        return 0
    sys.stdout.write(
        "   created_at           snapshot_id"
        + " " * 38 + "write_origin"
        + " " * 8 + "tool_name"
        + " " * 13 + "paths\n"
    )
    for s in snaps:
        sys.stdout.write(_fmt_row(s) + "\n")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = get_snapshot_store()
    snaps = store.list_snapshots()
    target = next((s for s in snaps if s.snapshot_id == args.snapshot_id), None)
    if target is None:
        sys.stderr.write(f"error: no snapshot with id {args.snapshot_id!r}\n")
        return 1
    sidecar = json.loads(target.sidecar_path.read_text(encoding="utf-8"))
    sys.stdout.write(json.dumps(sidecar, indent=2) + "\n")
    sys.stdout.write("\ntar contents:\n")
    try:
        with tarfile.open(target.tarball_path, "r:gz") as tf:
            for m in tf.getmembers():
                kind = "d" if m.isdir() else "f"
                sys.stdout.write(
                    f"  {kind} {m.size:>10} {m.name}\n"
                )
    except (tarfile.TarError, OSError) as e:
        sys.stderr.write(f"warning: could not read tarball: {e}\n")
    return 0


def cmd_pin(args: argparse.Namespace) -> int:
    ok = get_snapshot_store().pin(args.snapshot_id)
    if not ok:
        sys.stderr.write(f"error: no snapshot with id {args.snapshot_id!r}\n")
        return 1
    sys.stdout.write(f"pinned {args.snapshot_id}\n")
    return 0


def cmd_unpin(args: argparse.Namespace) -> int:
    ok = get_snapshot_store().unpin(args.snapshot_id)
    if not ok:
        sys.stderr.write(f"error: no snapshot with id {args.snapshot_id!r}\n")
        return 1
    sys.stdout.write(f"unpinned {args.snapshot_id}\n")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    store = get_snapshot_store()
    if args.dry_run:
        # Replicate prune's selection logic in a read-only form.
        snaps = store.list_snapshots()
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        cutoff = timedelta(days=store.retention_days)
        candidates = [
            s for s in snaps
            if not s.pinned and (now - s.created_at) > cutoff
        ]
        sys.stdout.write(
            f"dry-run: would remove {len(candidates)} of {len(snaps)} snapshots "
            f"(retention_days={store.retention_days}, "
            f"retention_count={store.retention_count}, "
            f"retention_bytes={store.retention_bytes})\n"
        )
        for s in candidates:
            sys.stdout.write(f"  - {s.snapshot_id}\n")
        return 0
    summary = store.prune()
    sys.stdout.write(
        f"removed={summary['removed']} "
        f"kept={summary['kept']} "
        f"pinned={summary['pinned']}\n"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena snapshot")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List snapshots, newest first.")
    p_list.add_argument("--write-origin", help="Filter by write_origin.")
    p_list.add_argument("--path", help="Filter to snapshots covering this path.")
    p_list.add_argument("--limit", type=int, help="Cap the number of rows.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(handler=cmd_list)

    p_show = sub.add_parser("show", help="Show sidecar + tar listing for one snapshot.")
    p_show.add_argument("snapshot_id")
    p_show.set_defaults(handler=cmd_show)

    p_pin = sub.add_parser("pin", help="Pin (exempt from prune).")
    p_pin.add_argument("snapshot_id")
    p_pin.set_defaults(handler=cmd_pin)

    p_unpin = sub.add_parser("unpin")
    p_unpin.add_argument("snapshot_id")
    p_unpin.set_defaults(handler=cmd_unpin)

    p_prune = sub.add_parser("prune", help="Apply retention policy.")
    p_prune.add_argument("--dry-run", action="store_true")
    p_prune.set_defaults(handler=cmd_prune)

    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
