"""``athena cache {status,clear}`` — cross-session prefix cache admin (T5-06.2).

Two subcommands:

  athena cache status [--json]   list every entry (workspace, prefix
                                  hash prefix, provider, age, ttl,
                                  alive)
  athena cache clear              empty the index

The cache itself is invalidated automatically by content hash; an
edited skill / system prompt → next session's prefix hashes
differently → the old entry simply isn't matched. ``clear`` is for
operators who want to force a clean slate (debugging a stale
backend cache id, switching providers, etc.).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..config import load_config, profile_dir

if TYPE_CHECKING:
    from ..cache import CrossSessionCache


def _resolve_index_path(args: argparse.Namespace) -> Path:
    cfg = load_config()
    if getattr(args, "index_path", None):
        return Path(args.index_path).expanduser()
    if cfg.cache_index_path:
        return Path(cfg.cache_index_path).expanduser()
    profile = getattr(args, "profile", None) or cfg.profile or "default"
    return profile_dir(profile) / "cache_index.json"


def _build_cache(path: Path) -> CrossSessionCache:
    from ..cache import CrossSessionCache

    cfg = load_config()
    return CrossSessionCache(index_path=path, cfg=cfg)


def cmd_status(args: argparse.Namespace) -> int:
    path = _resolve_index_path(args)
    if not path.exists():
        sys.stdout.write(f"no cache index at {path}\n")
        return 0
    cache = _build_cache(path)
    entries = cache.all()
    now = time.time()
    if args.json:
        payload = []
        for e in entries:
            payload.append(
                {
                    "workspace": e.workspace,
                    "prefix_hash": e.prefix_hash,
                    "provider": e.provider,
                    "provider_cache_id": e.provider_cache_id,
                    "ttl_s": e.ttl_s,
                    "created_at": e.created_at,
                    "age_s": int(now - e.created_at),
                    "alive": e.alive(now=now),
                }
            )
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    if not entries:
        sys.stdout.write("(no cache entries)\n")
        return 0
    sys.stdout.write(f"{len(entries)} cache entries in {path}:\n")
    for e in entries:
        age = int(now - e.created_at)
        alive = "ALIVE" if e.alive(now=now) else "EXPIRED"
        sys.stdout.write(
            f"  [{alive}] {e.workspace}  {e.provider}  hash={e.prefix_hash[:12]}…  "
            f"age={age}s  ttl={e.ttl_s}s\n"
        )
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    path = _resolve_index_path(args)
    if not path.exists():
        sys.stdout.write(f"no cache index at {path}; nothing to clear\n")
        return 0
    cache = _build_cache(path)
    n = cache.clear()
    sys.stdout.write(f"cleared {n} cache entry(ies) from {path}\n")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="athena cache",
        description=(
            "Cross-session prompt-cache admin. The cache is auto-"
            "invalidated by content hash; use clear only for a "
            "forced reset."
        ),
    )
    sub = ap.add_subparsers(dest="action", required=True)

    p_status = sub.add_parser("status", help="List cache entries.")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--profile")
    p_status.add_argument("--index-path", dest="index_path")
    p_status.set_defaults(func=cmd_status)

    p_clear = sub.add_parser("clear", help="Empty the cache index.")
    p_clear.add_argument("--profile")
    p_clear.add_argument("--index-path", dest="index_path")
    p_clear.set_defaults(func=cmd_clear)

    args = ap.parse_args(argv)
    return cast(int, args.func(args))
