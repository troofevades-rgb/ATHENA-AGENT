"""Interactive REPL — Ink TUI gateway + slash-command dispatch.

Extracted from ``athena/__main__.py`` 2026-06-01 as part of the
consolidation pass (see ``MEMORY.md → project-consolidation-pass``).
``__main__.py`` was 675 LOC and ``_run_interactive_repl`` was its
biggest single function (~205 LOC). The REPL is its own concern
(spawn the TUI subprocess, accept events from the gateway, dispatch
slash commands, surface tool output), so it belongs in its own
module.

Public surface:

  :func:`run_interactive_repl` -- main entry. Spawns the TUI,
    runs the event loop, returns the exit code. Called by
    ``athena/__main__.py:main()``.

  :func:`handle_slash` -- dispatches a slash-prefixed line to
    its ``@command``-decorated handler. Returns False to break
    out of the outer REPL loop (used for ``/exit /quit /q``);
    True to continue. Also called by ``athena/commands/loop.py``
    for nested ``/loop`` invocations.

The functions kept their private-prefixed names (``_handle_slash``,
``_run_interactive_repl``) as re-exports for one release so the
existing ``from ..__main__ import _handle_slash`` in
``commands/loop.py`` keeps working; the public names are the
new canonical entry points. The shim re-exports can be dropped
in the next release.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .. import commands, ui
from ..agent import Agent
from ..mcp import shutdown_all


def handle_slash(agent: Agent, line: str) -> bool:
    """Dispatch a slash-prefixed input line.

    Returns True if the outer REPL loop should continue, False to
    exit. The False return is reserved for the exit verbs
    (``/exit /quit /q``) which break the loop directly; every
    other command lives in ``athena/commands/*.py`` via the
    ``@command(...)`` decorator.
    """
    parts = line[1:].strip().split(maxsplit=1)
    if not parts:
        return True
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    # REPL-exit is hardcoded here (it controls the outer loop);
    # every other slash command lives in athena/commands/*.py via
    # the @command(...) decorator.
    if cmd in ("exit", "quit", "q"):
        return False

    fn = commands.get_command(cmd)
    if fn is None:
        ui.error(f"unknown command: /{cmd}. /help for list.")
        return True
    result = fn(agent, arg)
    # If the command returned a prompt string, run it as a user turn.
    if isinstance(result, str) and result:
        try:
            agent.run_turn(result)
        except KeyboardInterrupt:
            ui.warn("turn interrupted")
    return True


# Backwards-compatible alias for the one external caller that imports
# the private name from athena.__main__. Drop in the next release.
_handle_slash = handle_slash


def run_interactive_repl(agent: Agent, cfg: Any, workspace: Path) -> int:
    """Spawn the Ink TUI, drive the REPL through its gateway.

    All agent output (info / warn / error / tool calls / tool
    results) flows through ``ui.set_gateway()``'s event bridge to
    the Ink subprocess. Slash commands run inline in Python; their
    print output is bridged the same way.

    Returns the process exit code. Caller (``main()``) does
    ``sys.exit(rc)``.
    """
    import time as _time

    from ..tui_gateway import (
        MessageAppendEvent,
        StatusUpdateEvent,
        TuiGateway,
    )
    from ..tui_gateway.banner_data import build_banner
    from ..tui_gateway.events import (
        ConfirmReplyCommand,
        InterruptCommand,
        ResizeCommand,
        UserInputCommand,
    )

    session_start = _time.time()

    def _push_status() -> None:
        """Snapshot current counters and ship to the TUI."""
        try:
            stats = getattr(agent, "stats", None)
            up = getattr(stats, "prompt_tokens", 0) if stats else 0
            down = getattr(stats, "eval_tokens", 0) if stats else 0
            tool_counts = getattr(stats, "tool_call_counts", None) if stats else None
            tool_summary: str | None = None
            if tool_counts:
                top = sorted(tool_counts.items(), key=lambda kv: -kv[1])[:3]
                tool_summary = " / ".join(f"{name} {n}" for name, n in top if n > 0)
            # Plan mode is global agent state; read it fresh each
            # push so a tool-driven Enter/ExitPlanMode immediately
            # shows up in the TUI.
            try:
                from ..tools import plan as _plan

                in_plan = _plan.is_plan_mode()
            except Exception:  # noqa: BLE001
                in_plan = False
            gateway.send_event(
                StatusUpdateEvent(
                    model=agent.model,
                    profile=cfg.profile,
                    elapsed_seconds=_time.time() - session_start,
                    tokens_up=up,
                    tokens_down=down,
                    tool_summary=tool_summary,
                    plan_mode=in_plan,
                )
            )
        except Exception:  # noqa: BLE001 — never crash on UX writes
            pass

    # Plan-mode transitions ship an immediate status push to the
    # TUI so the user sees the read-only indicator the moment the
    # model calls EnterPlanMode mid-turn (instead of waiting for
    # the next natural _push_status between turns).
    try:
        from ..tools import plan as _plan_mod

        _plan_mod.register_plan_mode_listener(lambda _: _push_status())
    except Exception:  # noqa: BLE001 — registration is best-effort
        pass

    # The Ink TUI needs raw-mode stdin to capture single keypresses
    # and reuses the parent's stdout for its render. If either is
    # NOT a TTY (e.g. athena was invoked under a piped shell, a
    # non-PTY subprocess, an IDE's "run script" panel that emulates
    # stdin via a pipe, or msys/cygwin without ``winpty``), the
    # subprocess would crash with
    # ``Error: Raw mode is not supported on the current
    # process.stdin`` deep inside Ink's setRawMode. The parent
    # would then sit at "connecting to gateway…" until the 5s
    # accept-timeout fires and surface "TUI did not start —
    # bundle probably failed to start" -- misleading; the bundle
    # started fine but it inherited a broken stdio.
    #
    # Detect the situation up front and refuse with a clear
    # message + concrete next steps. ``ATHENA_TUI_NONINTERACTIVE``
    # is an escape hatch reserved for the pytest fixture that
    # exercises this branch (it monkeypatches the isatty check
    # AROUND the env var).
    if os.environ.get("ATHENA_TUI_NONINTERACTIVE") != "1":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            sys.stderr.write(
                "athena: cannot start the interactive TUI -- stdin or stdout "
                "is not a terminal.\n\n"
                "  The Ink TUI needs raw-mode stdin (single-keypress capture) "
                "and a real tty for rendering. Common causes:\n"
                "    * athena was launched from an IDE 'run' panel that "
                "pipes stdio\n"
                "    * a non-tty subprocess (e.g. ``echo hi | athena``)\n"
                "    * Git Bash / MSYS on Windows without ``winpty`` "
                "(try: winpty athena)\n\n"
                "  For one-shot non-interactive use, pass ``-p 'prompt'`` "
                "(headless mode skips the TUI entirely).\n"
            )
            return 2

    try:
        gateway = TuiGateway()
        gateway.start()
    except FileNotFoundError as e:
        sys.stderr.write(f"athena: {e}\n")
        sys.stderr.write("  Build the bundle with: cd ui-tui && bun run build\n")
        return 2
    except RuntimeError as e:
        sys.stderr.write(f"athena: TUI did not start — {e}\n")
        return 2

    ui.set_gateway(gateway)
    try:
        gateway.send_event(build_banner(model=agent.model, cwd=workspace, cfg=cfg))
        _push_status()
        while True:
            cmd = gateway.recv_command()
            if cmd is None:
                # TUI exited (Ctrl-C, /exit, socket closed).
                break
            if isinstance(cmd, ConfirmReplyCommand):
                # Route to the waiting ui.confirm() call. Doesn't
                # advance the REPL — the agent thread that called
                # confirm() will unblock and continue its turn.
                ui._deliver_confirm_reply(cmd.request_id, cmd.accepted)
                continue
            if isinstance(cmd, ResizeCommand):
                # TUI reported a new terminal size. Re-render the
                # banner so the owl photo matches the new width
                # (the rest of the banner is sized client-side on
                # every render via termCols, but the owl pixels
                # are baked Python-side when the banner is built).
                try:
                    gateway.send_event(
                        build_banner(
                            model=agent.model,
                            cwd=workspace,
                            cfg=cfg,
                            term_cols=cmd.cols,
                            term_rows=cmd.rows,
                        )
                    )
                except Exception:  # noqa: BLE001 — never crash on UX writes
                    pass
                continue
            if isinstance(cmd, InterruptCommand):
                # Ctrl+C at the idle prompt: exit cleanly. The
                # gateway enqueues InterruptCommand unconditionally
                # so this branch fires even when the queue.get()
                # was parked in a Windows condition-var wait that
                # _thread.interrupt_main() couldn't punch through.
                # The TUI already initiated its own exit() before
                # sending the interrupt; this break drops us into
                # the finally that closes the gateway and agent.
                break
            if not isinstance(cmd, UserInputCommand):
                # Other command types we don't act on (pong, etc.).
                continue
            line = cmd.text.strip()
            if not line:
                continue
            # Local echo so the user sees their line in the
            # transcript before the agent responds. Slash
            # commands don't echo since their handlers emit
            # their own user-visible output.
            if not line.startswith("/"):
                gateway.send_event(MessageAppendEvent(role="user", content=line))
            if line.startswith("/"):
                # Slash commands print user-facing output via
                # ``console.print``. The bridge only routes
                # those to the transcript inside this context;
                # agent-internal ``console.print`` during a
                # turn stays silent.
                with ui.user_facing_render():
                    if not handle_slash(agent, line):
                        break
                _push_status()
                continue
            try:
                agent.run_turn(line)
            except KeyboardInterrupt:
                ui.warn("turn interrupted")
            _push_status()
    except KeyboardInterrupt:
        # An ESC that arrives while we're between turns (idle in
        # recv_command) lands here. Treat it as a no-op — the user
        # is already at the prompt. Ctrl+C is what truly exits.
        ui.warn("interrupted")
    finally:
        ui.set_gateway(None)
        gateway.close()
        shutdown_all()
        agent.close()

    # If the gateway dropped us out of the loop because the Ink
    # subprocess crashed (rather than a clean /exit or Ctrl+C),
    # surface WHY — otherwise the user just lands back at the shell
    # prompt with no explanation ("it launched then sat there, then
    # quit"). Tail the captured Ink stderr so the actual error
    # (raw-mode failure, missing node module, JS exception) is right
    # there in the terminal.
    if getattr(gateway, "_child_crashed", False):
        _report_tui_crash(gateway)
        return 1
    return 0


def _report_tui_crash(gateway: Any) -> None:
    """Print a clear message + the tail of the Ink stderr capture
    after the TUI subprocess died unexpectedly."""
    sys.stderr.write("\nathena: the TUI exited unexpectedly (the Ink subprocess crashed).\n")
    path = getattr(gateway, "_tui_stderr_path", None)
    if not path or not Path(path).exists():
        sys.stderr.write("  No stderr capture was available.\n")
        return
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        sys.stderr.write(f"  Could not read {path}: {e}\n")
        return
    tail = [ln for ln in lines if ln.strip()][-15:]
    sys.stderr.write(f"  Last lines of {path}:\n")
    for ln in tail:
        sys.stderr.write(f"    {ln}\n")
    sys.stderr.write(
        "\n  If this is a 'Raw mode is not supported' error, your "
        "terminal isn't exposing a console stdin to the child.\n"
        "  Try launching from Windows Terminal (not an IDE 'run' "
        "panel), or run `athena doctor` for a full health check.\n"
    )


# Backwards-compatible alias. Drop in the next release.
_run_interactive_repl = run_interactive_repl


__all__ = (
    "handle_slash",
    "run_interactive_repl",
    "_handle_slash",
    "_run_interactive_repl",
)
