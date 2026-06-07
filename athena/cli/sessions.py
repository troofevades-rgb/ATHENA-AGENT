"""``athena sessions {list,browse,search,purge}`` — non-REPL session tools."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..config import CONFIG_DIR
from ..config import profile_dir as _profile_dir
from ..sessions.store import SessionStore


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena sessions")
    ap.add_argument("--profile", default="default")
    ap.add_argument(
        "--home", type=Path, default=None, help="Override athena home (default: ~/.athena)."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub_list = sub.add_parser("list", help="List recent sessions.")
    sub_list.add_argument("--limit", type=int, default=50)

    sub_browse = sub.add_parser("browse", help="Print a session's messages.")
    sub_browse.add_argument("session_id")
    sub_browse.add_argument("--from-turn", type=int, default=0)
    sub_browse.add_argument("--limit", type=int, default=200)

    sub_search = sub.add_parser("search", help="Full-text search across sessions.")
    sub_search.add_argument("query")
    sub_search.add_argument("--k", type=int, default=10)
    sub_search.add_argument("--workspace", default=None)

    sub_purge = sub.add_parser("purge", help="Delete sessions older than a cutoff.")
    sub_purge.add_argument("--before", required=True, help="ISO date (YYYY-MM-DD).")
    sub_purge.add_argument(
        "--confirm", action="store_true", help="Required — purge is irreversible."
    )

    sub_verify = sub.add_parser(
        "verify",
        help="Check JSONL ↔ SQLite-index consistency per session (drift detector).",
    )
    sub_verify.add_argument("--json", action="store_true", help="Machine-readable output.")

    return ap


def _store(args: argparse.Namespace) -> SessionStore:
    home = args.home.expanduser().resolve() if args.home else CONFIG_DIR
    return SessionStore(_profile_dir(args.profile, home))


def _cmd_list(args: argparse.Namespace, store: SessionStore) -> int:
    sessions = store.list_sessions(limit=args.limit)
    if not sessions:
        print("(no sessions)")
        return 0
    for m in sessions:
        started = m.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        ended = (
            "active"
            if m.ended_at is None
            else m.ended_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        )
        ws = m.workspace or "-"
        print(f"{m.session_id}  {started} → {ended}  model={m.model}  ws={ws}")
    return 0


def _cmd_browse(args: argparse.Namespace, store: SessionStore) -> int:
    # Show fork lineage at the top so the user knows what they're inside of.
    children = store.children(args.session_id)
    if children:
        print(f"Session {args.session_id}")
        for child in children:
            ws = child.workspace or "-"
            started = child.started_at.strftime("%Y-%m-%d %H:%M") if child.started_at else "?"
            print(f"  └─ fork {child.session_id} ({started}, ws={ws})")
        print()

    count = 0
    shown = 0
    for i, msg in enumerate(store.load(args.session_id)):
        if i < args.from_turn:
            continue
        count += 1
        if shown >= args.limit:
            print(f"... (limit {args.limit} reached; pass --from-turn {i} to continue)")
            break
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        print(f"--- turn {i} [{role}] ---")
        print(content)
        print()
        shown += 1
    if count == 0 and not children:
        print(f"(no messages from turn {args.from_turn} onward; check `athena sessions list`)")
    return 0


def _cmd_search(args: argparse.Namespace, store: SessionStore) -> int:
    workspace = None if args.workspace == "" else args.workspace
    hits = store.search(args.query, k=args.k, workspace=workspace)
    if not hits:
        print(f"(no matches for {args.query!r})")
        return 0
    for h in hits:
        started = h.started_at.strftime("%Y-%m-%d %H:%M")
        print(f"{h.session_id} [{h.role}] {started}: {h.snippet}")
    return 0


def _cmd_purge(args: argparse.Namespace, store: SessionStore) -> int:
    if not args.confirm:
        print("error: --confirm required (purge is irreversible)", file=sys.stderr)
        return 2
    try:
        cutoff = datetime.fromisoformat(args.before)
    except ValueError as e:
        print(f"error: --before is not a valid ISO date: {e}", file=sys.stderr)
        return 2
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    older = store.list_sessions(limit=10_000, before=cutoff)
    if not older:
        print("(nothing to purge)")
        return 0
    for m in older:
        for suffix in (".jsonl", ".meta.json"):
            p = store.sessions_dir / f"{m.session_id}{suffix}"
            if p.exists():
                p.unlink()
        conn = store._conn()
        conn.execute("DELETE FROM turns WHERE session_id = ?", (m.session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (m.session_id,))
    store._conn().commit()
    print(f"purged {len(older)} session(s) before {cutoff.isoformat()}")
    return 0


def _cmd_verify(args: argparse.Namespace, store: SessionStore) -> int:
    rows = store.verify()
    if args.json:
        import json as _json
        from dataclasses import asdict

        print(_json.dumps([asdict(r) for r in rows], indent=2))
    else:
        if not rows:
            print("(no sessions)")
        for r in rows:
            if r.ok:
                continue
            if r.jsonl_turns < 0:
                reason = "indexed but no JSONL file (truth missing)"
            elif not r.indexed:
                reason = f"JSONL present ({r.jsonl_turns} turns) but no sessions-table row"
            else:
                reason = f"drift: {r.jsonl_turns} JSONL turn(s) vs {r.db_turns} indexed"
            print(f"{r.session_id}  {reason}")
    bad = [r for r in rows if not r.ok]
    ok_n = len(rows) - len(bad)
    print(
        f"{ok_n}/{len(rows)} session(s) consistent"
        + (f"; {len(bad)} need attention — run `athena reindex`" if bad else ""),
        file=sys.stderr,
    )
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    store = _store(args)
    try:
        if args.cmd == "list":
            return _cmd_list(args, store)
        if args.cmd == "browse":
            return _cmd_browse(args, store)
        if args.cmd == "search":
            return _cmd_search(args, store)
        if args.cmd == "purge":
            return _cmd_purge(args, store)
        if args.cmd == "verify":
            return _cmd_verify(args, store)
        return 2
    finally:
        store.close()
