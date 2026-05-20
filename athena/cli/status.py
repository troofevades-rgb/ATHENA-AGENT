"""``athena status [--profile <name>] [--json]``.

Read-only view of the live counters for the active profile. Reads
``<profile_dir>/.status.json`` — written atomically by every
running agent's :meth:`Agent.write_status_snapshot` at the end of
each turn. Reading this file never mutates anything.

The renderer (:func:`render_status`) is also imported by the REPL's
``/status`` slash command so the two surfaces stay byte-identical.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ..config import load_config, profile_dir
from ..profiles.resolution import resolve_active_profile


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    profile = resolve_active_profile(
        cli_arg=args.profile,
        config_default=cfg.profile,
    )
    snapshot_path = profile_dir(profile) / ".status.json"
    if not snapshot_path.exists():
        msg = f"no live athena process for profile {profile!r} (no .status.json snapshot found)"
        if args.json:
            sys.stdout.write(
                json.dumps({"active": False, "profile": profile}) + "\n",
            )
            return 0
        sys.stdout.write(msg + "\n")
        return 0
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"error: failed to read {snapshot_path}: {e}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(snapshot, indent=2) + "\n")
        return 0
    sys.stdout.write(render_status(snapshot) + "\n")
    return 0


def render_status(snapshot: dict[str, Any]) -> str:
    """Format a snapshot dict for human display.

    Single function used by both ``athena status`` and the REPL's
    ``/status`` slash command — the rendering stays consistent
    regardless of which surface you call it from.
    """
    lines: list[str] = []
    lines.append(f"profile:  {snapshot.get('profile', '?')}")
    lines.append(f"session:  {snapshot.get('session_id') or 'n/a'}")
    lines.append(f"model:    {snapshot.get('model', '?')}")
    lines.append(f"provider: {snapshot.get('provider', '?')}")
    elapsed = snapshot.get("elapsed_seconds")
    if elapsed is not None:
        lines.append(f"elapsed:  {_human_duration(float(elapsed))}")
    lines.append("")

    lines.append("tokens:")
    lines.append(f"  prompt:     {snapshot.get('prompt_tokens', 0):>8}")
    lines.append(f"  completion: {snapshot.get('completion_tokens', 0):>8}")
    lines.append(f"  total:      {snapshot.get('total_tokens', 0):>8}")
    cache_read = snapshot.get("cache_read_tokens", 0)
    cache_creation = snapshot.get("cache_creation_tokens", 0)
    if cache_read or cache_creation:
        lines.append(f"  cache read: {cache_read:>8}")
        lines.append(f"  cache new:  {cache_creation:>8}")
    cache_strategy = snapshot.get("cache_strategy")
    if cache_strategy:
        ttl = snapshot.get("prompt_cache_ttl", "5m")
        lines.append(f"  strategy:   {cache_strategy} (ttl {ttl})")
    lines.append("")

    lines.append(f"turns:        {snapshot.get('turns', 0):>4}")
    lines.append(f"tool calls:   {snapshot.get('tool_calls', 0):>4}")
    lines.append(f"forks:        {snapshot.get('fork_count', 0):>4}")
    lines.append(f"reviews:      {snapshot.get('review_fired_count', 0):>4}")
    lines.append(f"curator runs: {snapshot.get('curator_run_count', 0):>4}")

    tool_counts = snapshot.get("tool_call_counts") or {}
    if tool_counts:
        lines.append("")
        lines.append("tool histogram:")
        # Sorted by count desc — most-used at top, easier to spot
        # which tool is dominating a turn.
        for tool, count in sorted(
            tool_counts.items(),
            key=lambda kv: -int(kv[1]),
        ):
            lines.append(f"  {tool:<20} {count:>4}")

    # T2-02: rate-limit state per credential.
    rate_limits = snapshot.get("rate_limits") or {}
    if rate_limits:
        lines.append("")
        lines.append("rate limits:")
        for cred_id, formatted in rate_limits.items():
            lines.append(f"  {cred_id}: {formatted}")
    return "\n".join(lines)


def _human_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m{s:02d}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m"


# ---- argument parser ----------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena status")
    ap.add_argument(
        "--profile",
        help="Profile whose status to read (default: active).",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="JSON output for scripting.",
    )
    ap.set_defaults(handler=cmd_status)
    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
