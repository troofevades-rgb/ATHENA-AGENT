"""``/computer`` — status + admin for the computer-use feature (T6-04.4).

A slash command + a callable that prints the operator-facing
status block: which backend is selected, which actions it
supports, the current permission mode, the allow / denylist,
and a tail of the audit log.

Read-only — does not change any setting. Use ``/config`` to
adjust the underlying knobs.
"""

from __future__ import annotations

from .. import ui
from ..computer.detect import available_backends, select_backend
from ..computer.audit import default_audit_path, ActionAuditLog
from ..config import load_config, profile_dir
from . import command


def _print_status(*, tail_n: int = 5) -> None:
    cfg = load_config()
    cu = cfg.computer
    enabled = bool(cu.use_enabled)
    ui.console.print(
        f"[bold]computer use:[/] "
        f"{'[green]enabled[/]' if enabled else '[red]disabled[/]'} "
        f"(use_enabled={enabled})"
    )

    ui.console.print(f"  mode: [bold]{cu.permission_mode}[/]")

    allow = list(cu.app_allowlist or [])
    deny = list(cu.app_denylist or [])
    ui.console.print(
        f"  allowlist: {allow if allow else '[dim](empty — no app may be controlled)[/]'}"
    )
    ui.console.print(f"  denylist:  {deny}")
    ui.console.print(
        f"  kill hotkey: {cu.kill_hotkey} (Ctrl+C always active)"
    )
    ui.console.print(
        f"  caps: max_actions/task={cu.max_actions_per_task}, "
        f"max_actions/sec={cu.max_actions_per_sec}"
    )

    backend = select_backend(cfg)
    avail = backend.is_available()
    ui.console.print(
        f"  active backend: [bold]{backend.name}[/] "
        f"({'available' if avail else '[red]unavailable on this host[/]'})"
    )
    ui.console.print(f"    supports: {backend.supports() or '[dim](none)[/]'}")

    ui.console.print("  known backends:")
    for row in available_backends():
        marker = "✓" if row["available"] else "✗"
        ui.console.print(
            f"    {marker} {row['name']}: supports={row['supports']}"
        )

    # Audit log tail.
    prof = getattr(cfg, "profile", None) or "default"
    audit_path = default_audit_path(cfg, profile_dir(prof))
    ui.console.print(f"  audit log: {audit_path}")
    audit = ActionAuditLog(audit_path)
    entries = audit.tail(limit=tail_n)
    if not entries:
        ui.console.print("    (no entries yet)")
        return
    ui.console.print(f"  recent actions (last {len(entries)}):")
    for e in entries:
        result_color = (
            "green" if e.executed and e.result == "ok"
            else "yellow" if not e.executed
            else "red"
        )
        ui.console.print(
            f"    [{e.ts}] {e.type} tier={e.tier} "
            f"app={e.app!r} → [{result_color}]{e.result}[/]"
        )


@command("computer")
def cmd_computer(agent, arg: str = "") -> str:
    """``/computer`` slash command — status by default; ``status``
    is the explicit form."""
    arg = (arg or "").strip().lower()
    if arg in ("", "status"):
        _print_status()
    else:
        ui.error(f"unknown /computer subcommand: {arg!r} (use 'status')")
    return ""


def main(argv: list[str]) -> int:
    """``athena computer status`` CLI entry."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="athena computer",
        description="Computer-use status + admin",
    )
    sub = ap.add_subparsers(dest="action")
    p_status = sub.add_parser("status", help="Show backend + mode + audit tail")
    p_status.add_argument("--tail", type=int, default=5)
    args = ap.parse_args(argv)

    action = args.action or "status"
    if action == "status":
        _print_status(tail_n=int(getattr(args, "tail", 5)))
        return 0
    ap.print_help()
    return 2
