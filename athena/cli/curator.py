"""``athena curator {run,status,pause,resume,inspect-last}``.

The CLI builds a thin agent shell (no chat loop) so the curator can run
without going through the REPL. ``run`` may be invoked headlessly under
``--no-confirm`` or by a cron job; the other verbs are read/write
shortcuts to the persistent state and the latest report directory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from ..config import CONFIG_DIR, profile_dir
from ..curator import state as curator_state

# We don't need the full Agent for headless curator runs; a SimpleNamespace
# carrying the few fields maybe_run_curator inspects is enough.


def _build_agent_shell(profile: str, home: Path | None):
    from ..config import load_config

    cfg = load_config()
    cfg.profile = profile
    home = home or CONFIG_DIR
    from ..sessions.store import SessionStore

    store = SessionStore(profile_dir(profile, home))
    return SimpleNamespace(
        cfg=cfg,
        session_id=None,
        session_store=store,
        workspace=Path.cwd().resolve(),
        client=None,
        model=cfg.model,
        # fork() reads parent.messages to pin the child's system
        # prompt for prefix-cache parity. The headless curator has no
        # conversation to inherit from — an empty list makes fork()
        # fall through to the child's default system prompt instead
        # of blowing up with AttributeError.
        messages=[],
    )


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena curator")
    ap.add_argument("--profile", default="default")
    ap.add_argument(
        "--home", type=Path, default=None, help="Override athena home (default: ~/.athena)."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub_run = sub.add_parser("run", help="Run the curator now (subject to gates).")
    sub_run.add_argument("--dry-run", action="store_true")
    sub_run.add_argument("--force", action="store_true", help="Bypass interval and idle gates.")

    sub.add_parser("status", help="Show last_run_at / run_count / paused.")
    sub.add_parser("pause", help="Pause the curator (gates never pass until resume).")
    sub.add_parser("resume", help="Resume after pause.")
    sub.add_parser("inspect-last", help="Print the path and body of the most recent REPORT.md.")
    return ap


def _skills_root(home: Path | None) -> Path:
    return (home or CONFIG_DIR) / "skills"


def _logs_root(home: Path | None) -> Path:
    return (home or CONFIG_DIR) / "logs"


def _cmd_run(args) -> int:
    # Run the curator with the configured logs path via monkey patch on the
    # orchestrator's helper. Simpler: import the helper and let it stay
    # default (CONFIG_DIR). For --home override we set CONFIG_DIR.
    from ..curator.orchestrator import maybe_run_curator

    home = args.home.expanduser().resolve() if args.home else None
    if home is not None:
        from ..curator import orchestrator as orch

        orch.CONFIG_DIR = home  # type: ignore[attr-defined]

    agent = _build_agent_shell(args.profile, home)
    try:
        summary = maybe_run_curator(agent, force=args.force, dry_run=args.dry_run)
    finally:
        try:
            agent.session_store.close()
        except Exception:
            pass

    if summary is None:
        print("Curator did not run (gates not met; use --force to override).")
        return 1

    print(f"Curator run complete. Report: {summary['report_path']}")
    print(f"Total skills reviewed: {summary['total_skills']}")
    for decision, count in sorted(summary["decision_counts"].items()):
        targets = summary["targets_by_decision"].get(decision)
        suffix = f" ({', '.join(sorted(set(targets)))})" if targets else ""
        print(f"  {decision}: {count}{suffix}")
    return 0


def _cmd_status(args) -> int:
    home = args.home.expanduser().resolve() if args.home else None
    s = curator_state.read_state(_skills_root(home))
    print(
        json.dumps(
            {
                "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                "run_count": s.run_count,
                "paused": s.paused,
            },
            indent=2,
        )
    )
    return 0


def _set_paused(args, paused: bool) -> int:
    home = args.home.expanduser().resolve() if args.home else None
    root = _skills_root(home)
    s = curator_state.read_state(root)
    curator_state.write_state(
        root,
        curator_state.State(
            last_run_at=s.last_run_at,
            run_count=s.run_count,
            paused=paused,
        ),
    )
    print(f"curator paused={paused}")
    return 0


def _cmd_inspect_last(args) -> int:
    home = args.home.expanduser().resolve() if args.home else None
    logs = _logs_root(home) / "curator"
    if not logs.exists():
        print("(no curator runs yet)")
        return 1
    runs = sorted(p for p in logs.iterdir() if p.is_dir())
    if not runs:
        print("(no curator runs yet)")
        return 1
    latest = runs[-1]
    report = latest / "REPORT.md"
    if not report.exists():
        print(f"(latest run dir has no REPORT.md: {latest})")
        return 1
    print(f"# {report}\n")
    print(report.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "status":
        return _cmd_status(args)
    if args.cmd == "pause":
        return _set_paused(args, True)
    if args.cmd == "resume":
        return _set_paused(args, False)
    if args.cmd == "inspect-last":
        return _cmd_inspect_last(args)
    return 2
