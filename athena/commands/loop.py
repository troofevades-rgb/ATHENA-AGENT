"""/loop — re-run a prompt or slash command on a fixed interval.

Usage:
  /loop 5m /review
  /loop 30s check the build status

A single loop runs at a time; calling /loop again replaces it. The runner
uses the agent's _turn_lock so it can't interleave with the REPL, and uses
prompt_toolkit's run_in_terminal so output doesn't corrupt the user's prompt.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from .. import ui
from . import command

_LOOP: dict[str, Any] | None = None

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smh]?)\s*(.*)$", re.S)


def _parse(arg: str) -> tuple[float, str] | None:
    m = _INTERVAL_RE.match(arg)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "m"
    body = m.group(3).strip()
    if not body:
        return None
    multiplier = {"s": 1, "m": 60, "h": 3600}[unit]
    return float(n * multiplier), body


def _run_iteration(agent, body: str) -> None:
    def _do() -> None:
        try:
            if body.startswith("/"):
                from ..__main__ import _handle_slash

                _handle_slash(agent, body)
            else:
                agent.run_turn(body)
        except Exception as e:
            ui.error(f"loop iteration failed: {e}")

    # Pause the active prompt so streamed output doesn't tear the input line.
    # If no prompt session is running (one-shot mode, etc.), run inline.
    try:
        from prompt_toolkit.application import run_in_terminal
        from prompt_toolkit.application.current import get_app_or_none

        app = get_app_or_none()
        if app is not None and app.is_running:
            future = run_in_terminal(_do)
            future.result()
            return
    except Exception:
        pass
    _do()


@command("loop")
def cmd_loop(agent, arg: str = "") -> str:
    global _LOOP
    parsed = _parse(arg)
    if not parsed:
        ui.error("usage: /loop <interval> <prompt>   e.g. /loop 5m /review")
        return ""
    interval, body = parsed

    if _LOOP is not None:
        ui.warn("replacing existing loop")
        _LOOP["stop"].set()

    stop = threading.Event()

    def _runner() -> None:
        ticks = 0
        # Event.wait returns True if set during the wait, False on timeout.
        while not stop.wait(interval):
            ticks += 1
            ui.console.print(f"\n[bold cyan]── /loop tick #{ticks} ({body!r}) ──[/]\n")
            _run_iteration(agent, body)

    # Snapshot the foreground context so write_origin, approval
    # callback, and any other ContextVars set in the REPL propagate
    # into the loop thread. Plain ``threading.Thread`` does NOT copy
    # ContextVars; the loop body would otherwise see defaults --
    # critically, a gateway-installed approval router on the
    # foreground would not be visible inside the loop's tool calls.
    import contextvars as _ctx
    _foreground_ctx = _ctx.copy_context()

    def _entry() -> None:
        _foreground_ctx.run(_runner)

    th = threading.Thread(target=_entry, name="athena-loop", daemon=True)
    _LOOP = {"stop": stop, "thread": th, "body": body, "interval": interval}
    th.start()
    ui.info(f"loop scheduled: every {interval:.0f}s -> {body!r}. /loop-stop to cancel.")
    return ""


@command("loop-stop")
def cmd_loop_stop(agent, arg: str = "") -> str:
    global _LOOP
    if _LOOP is None:
        ui.info("no loop running")
        return ""
    _LOOP["stop"].set()
    _LOOP = None
    ui.info("loop stopped")
    return ""
