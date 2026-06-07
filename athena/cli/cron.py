"""``athena cron {add,list,remove,enable,disable,run-now,logs,daemon}``.

The CLI talks to the same SQLite-backed :class:`CronScheduler` the daemon
uses. ``add``/``remove``/``enable``/``disable`` write to the metadata
store; the running daemon picks up changes on its next polling pass (or
immediately if the daemon process is the one running the command).

``daemon`` runs the scheduler in foreground until Ctrl-C — suitable for
local dev. Production setups would launch it as a systemd unit.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import CONFIG_DIR
from ..cron.jobs import CronJob, JobStore
from ..cron.runner import run_agent_job
from ..cron.scheduler import CronScheduler
from ..cron.watchdog import run_watchdog_job

if TYPE_CHECKING:
    from types import FrameType


def _default_paths() -> tuple[Path, Path]:
    """Return (scheduler_db, jobs_db) aligned with the runner / watchdog.

    Both cron databases were moved into ``profiles/<profile>/`` by the
    auto-migration shipped in `athena/profiles/migration.py:45-46`. The
    CLI was still hardcoding ``CONFIG_DIR / cron.db`` so after
    migration the CLI saw an empty global path while the daemon's
    schedule lived at the profile path. Resolve via the same helper
    the runner uses so both sides agree.
    """
    sched, jobs = _profile_cron_paths()
    return (sched, jobs)


def _profile_cron_paths() -> tuple[Path, Path]:
    """Per-profile cron paths with legacy fallback. Importable from
    runner/watchdog so APScheduler-side dispatch agrees with the CLI."""
    try:
        from ..config import load_config, profile_dir

        cfg = load_config()
        profile = getattr(cfg, "profile", None) or "default"
        pdir = profile_dir(profile)
        sched = pdir / "cron.db"
        jobs = pdir / "cron_jobs.db"
        # If the profile-keyed DBs don't exist but the legacy ones do,
        # the migration never ran (or only partially); fall back to
        # CONFIG_DIR so the operator's existing jobs stay reachable
        # until the next start-time migration sweep moves them.
        if not sched.exists() and not jobs.exists():
            legacy_sched = CONFIG_DIR / "cron.db"
            legacy_jobs = CONFIG_DIR / "cron_jobs.db"
            if legacy_sched.exists() or legacy_jobs.exists():
                return (legacy_sched, legacy_jobs)
        return (sched, jobs)
    except Exception:
        # Pathological config; fall back to legacy paths rather than
        # crash the CLI.
        return (CONFIG_DIR / "cron.db", CONFIG_DIR / "cron_jobs.db")


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena cron")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add a scheduled job.")
    p_add.add_argument("--schedule", required=True, help="Cron expression, e.g. '0 9 * * *'.")
    p_add.add_argument("--skill", help="Agent mode: skill name to invoke.")
    p_add.add_argument("--prompt", help="Agent mode: explicit prompt.")
    p_add.add_argument("--script", help="Watchdog mode: shell command.")
    p_add.add_argument(
        "--deliver",
        default="log",
        help="Delivery target: log | file:<path> | gateway://platform/chat_id (Phase 10).",
    )
    p_add.add_argument("--description", default="")

    sub.add_parser("list", help="List every scheduled job.")

    for verb in ("remove", "enable", "disable", "run-now"):
        p = sub.add_parser(verb, help=f"{verb} a job by ID.")
        p.add_argument("job_id")

    p_logs = sub.add_parser("logs", help="Show recent runs for a job (last_status only).")
    p_logs.add_argument("job_id")
    p_logs.add_argument("--tail", type=int, default=10)

    p_daemon = sub.add_parser("daemon", help="Run the scheduler in foreground.")
    p_daemon.add_argument(
        "--once",
        action="store_true",
        help="Start, register every persisted job, then exit (test affordance).",
    )

    return ap


def _select_mode(args: argparse.Namespace) -> str:
    if args.script:
        if args.skill or args.prompt:
            raise SystemExit("error: --script is mutually exclusive with --skill/--prompt")
        return "watchdog"
    if args.skill or args.prompt:
        return "agent"
    raise SystemExit("error: one of --skill, --prompt, or --script is required")


def _open_scheduler() -> CronScheduler:
    sched_db, jobs_db = _default_paths()
    return CronScheduler(db_path=sched_db, jobs_db_path=jobs_db)


def _cmd_add(args: argparse.Namespace) -> int:
    mode = _select_mode(args)
    try:
        job = CronJob(
            cron_expr=args.schedule,
            mode=mode,
            description=args.description,
            skill=args.skill,
            prompt=args.prompt,
            script=args.script,
            delivery_target=args.deliver,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    scheduler = _open_scheduler()
    try:
        scheduler.add_job(job)
    finally:
        scheduler.stop()
    print(f"added cron job {job.id}  ({mode}, '{args.schedule}')")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    sched_db, jobs_db = _default_paths()
    store = JobStore(jobs_db)
    jobs = store.list_jobs()
    if not jobs:
        print("(no cron jobs)")
        return 0
    scheduler = _open_scheduler()
    try:
        scheduler.start()
        for j in jobs:
            next_run = scheduler.next_run_time(j.id) if j.enabled else None
            next_str = next_run.isoformat() if next_run else "—"
            target = j.skill or (j.prompt or "")[:40] or (j.script or "")[:40]
            state = "on" if j.enabled else "off"
            print(f"{j.id[:8]}  {state}  '{j.cron_expr}'  {j.mode}  next={next_str}  {target}")
    finally:
        scheduler.stop()
    return 0


def _resolve_id(store: JobStore, prefix_or_id: str) -> CronJob | None:
    """Accept either a full UUID or an unambiguous prefix."""
    if (exact := store.get(prefix_or_id)) is not None:
        return exact
    matches = [j for j in store.list_jobs() if j.id.startswith(prefix_or_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(
            f"error: prefix {prefix_or_id!r} is ambiguous: {', '.join(m.id[:8] for m in matches)}",
            file=sys.stderr,
        )
    return None


def _cmd_remove(args: argparse.Namespace) -> int:
    scheduler = _open_scheduler()
    try:
        job = _resolve_id(scheduler.store, args.job_id)
        if job is None:
            print(f"error: no job matching {args.job_id!r}", file=sys.stderr)
            return 2
        scheduler.remove_job(job.id)
    finally:
        scheduler.stop()
    print(f"removed {job.id}")
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    scheduler = _open_scheduler()
    try:
        job = _resolve_id(scheduler.store, args.job_id)
        if job is None:
            print(f"error: no job matching {args.job_id!r}", file=sys.stderr)
            return 2
        scheduler.start()
        scheduler.enable(job.id)
    finally:
        scheduler.stop()
    print(f"enabled {job.id}")
    return 0


def _cmd_disable(args: argparse.Namespace) -> int:
    scheduler = _open_scheduler()
    try:
        job = _resolve_id(scheduler.store, args.job_id)
        if job is None:
            print(f"error: no job matching {args.job_id!r}", file=sys.stderr)
            return 2
        scheduler.start()
        scheduler.disable(job.id)
    finally:
        scheduler.stop()
    print(f"disabled {job.id}")
    return 0


def _cmd_run_now(args: argparse.Namespace) -> int:
    _, jobs_db = _default_paths()
    store = JobStore(jobs_db)
    job = _resolve_id(store, args.job_id)
    if job is None:
        print(f"error: no job matching {args.job_id!r}", file=sys.stderr)
        return 2
    if job.mode == "watchdog":
        result = run_watchdog_job(job, store=store)
    else:
        result = run_agent_job(job, store=store)
    print(json.dumps(result, default=str, indent=2))
    return 0 if result.get("status") == "success" else 1


def _cmd_logs(args: argparse.Namespace) -> int:
    _, jobs_db = _default_paths()
    store = JobStore(jobs_db)
    job = _resolve_id(store, args.job_id)
    if job is None:
        print(f"error: no job matching {args.job_id!r}", file=sys.stderr)
        return 2
    when = job.last_run_at.isoformat() if job.last_run_at else "—"
    status = job.last_status or "—"
    print(f"job:    {job.id}")
    print(f"mode:   {job.mode}")
    print(f"sched:  '{job.cron_expr}'")
    print(f"last:   {when}  ({status})")
    print(
        "(detailed per-run logs land with the file delivery target; "
        "for richer history switch --deliver to file:<path>)"
    )
    return 0


def _cmd_daemon(args: argparse.Namespace) -> int:
    scheduler = _open_scheduler()
    scheduler.start()
    jobs = scheduler.list_jobs()
    enabled = sum(1 for j in jobs if j.enabled)
    print(f"cron daemon started — {enabled}/{len(jobs)} jobs enabled. Press Ctrl-C to stop.")
    if args.once:
        scheduler.stop()
        return 0

    stop_event = {"stopped": False}

    def _on_sig(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001
        stop_event["stopped"] = True

    signal.signal(signal.SIGINT, _on_sig)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_sig)

    try:
        while not stop_event["stopped"]:
            time.sleep(0.5)
    finally:
        scheduler.stop()
    print("cron daemon stopped")
    return 0


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "add":
        return _cmd_add(args)
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "remove":
        return _cmd_remove(args)
    if args.cmd == "enable":
        return _cmd_enable(args)
    if args.cmd == "disable":
        return _cmd_disable(args)
    if args.cmd == "run-now":
        return _cmd_run_now(args)
    if args.cmd == "logs":
        return _cmd_logs(args)
    if args.cmd == "daemon":
        return _cmd_daemon(args)
    return 2
