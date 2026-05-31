"""CLI entry point. Handles argument parsing, REPL, and slash commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import commands, tools, ui
from .agent import Agent
from .config import CONFIG_DIR, SESSIONS_DIR, load_config, mcp_config_paths
from .mcp import load_mcp_servers, shutdown_all
from .mcp.loader import active_clients


def _normalize_model_name(name: str) -> str:
    """Ollama treats 'foo' and 'foo:latest' as the same model. Normalize so
    the pulled-model check doesn't false-alarm on tag mismatch."""
    return name if ":" in name else f"{name}:latest"


def _model_pulled(want: str, available: list[str]) -> bool:
    target = _normalize_model_name(want)
    return any(_normalize_model_name(m) == target for m in available)


def _rewrite_singledash_longs(argv: list[str], parser: argparse.ArgumentParser) -> list[str]:
    """Rewrite ``-foo`` -> ``--foo`` when ``--foo`` is a known long-form
    flag on ``parser`` (and ``-foo`` is NOT a known short flag like ``-m``).

    Catches the common typo ``athena -model NAME`` (which argparse
    would otherwise parse as ``-m`` with value ``odel`` plus an
    unrecognised positional). Suggests a close match for unknown
    single-dash multi-char tokens.
    """
    import difflib

    long_forms: set[str] = set()
    short_forms: set[str] = set()
    for action in parser._actions:  # type: ignore[attr-defined]
        for opt in action.option_strings:
            if opt.startswith("--"):
                long_forms.add(opt[2:])
            elif opt.startswith("-") and len(opt) == 2:
                short_forms.add(opt[1:])
    out: list[str] = []
    for token in argv:
        if (
            token.startswith("-")
            and not token.startswith("--")
            and len(token) > 2
            and token[1:].split("=")[0] not in short_forms
        ):
            key = token[1:].split("=")[0]
            if key in long_forms:
                # Pure rewrite — argparse handles it.
                out.append("-" + token)
                continue
            close = difflib.get_close_matches(key, sorted(long_forms), n=1, cutoff=0.7)
            if close:
                sys.stderr.write(f"athena: did you mean --{close[0]} (you wrote -{key})?\n")
        out.append(token)
    return out


def _handle_slash(agent: Agent, line: str) -> bool:
    """Returns True if the loop should continue, False to exit."""
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


_SUBCOMMANDS = {
    "import-from-hermes": "athena.cli.import_hermes",
    "reindex": "athena.cli.reindex",
    "sessions": "athena.cli.sessions",
    "curator": "athena.cli.curator",
    "plugins": "athena.cli.plugins",
    "cron": "athena.cli.cron",
    "model": "athena.cli.model",
    "train": "athena.cli.train",
    "providers": "athena.cli.providers",
    "cleanup-blobs": "athena.cli.cleanup_blobs",
    "gateway": "athena.cli.gateway",
    "mcp": "athena.cli.mcp",
    "acp": "athena.cli.acp",
    "profile": "athena.cli.profile",
    "webhook": "athena.cli.webhook",
    "status": "athena.cli.status",
    "snapshot": "athena.cli.snapshot",
    "skill": "athena.cli.skill",
    "memory": "athena.cli.memory",
    "proxy": "athena.cli.proxy",
    "checkpoint": "athena.cli.checkpoint",
    "audit": "athena.cli.audit",
    "verify": "athena.cli.verify",
    "doctor": "athena.cli.doctor",
    "cache": "athena.cli.cache",
    "recall": "athena.cli.recall",
    "image-demo": "athena.cli.image_demo",
    "theme": "athena.cli.theme",
    "wordmark": "athena.cli.wordmark",
    "computer": "athena.commands.computer",
    "board": "athena.commands.board",
    "update": "athena.commands.update",
    # T7-02: batch_runner iterating the T7-01 headless primitive.
    "batch": "athena.cli.batch",
    # T6-03 admin: verify the cli_delegate_command config + a
    # one-shot codex setup helper.
    "delegate": "athena.cli.delegate",
    # T7-03: eval-battery composing batch + scoring + baseline diff.
    "eval": "athena.cli.eval",
}


def _json_invalid_envelope(
    error: str,
    args: Any,
    cfg: Any,
    workspace: Path,
) -> str:
    """Build a status='invalid' RunResult JSON for the early
    validation paths in main() (before run_headless is called).
    Keeps the envelope shape consistent so a batch caller
    parsing --json output always gets a valid envelope, even
    on failures upstream of the runner.
    """
    import datetime

    from .headless.result import RunResult, mint_run_id

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    rid = getattr(args, "run_id", None) or mint_run_id()
    return RunResult(
        run_id=rid,
        status="invalid",
        started_at=now,
        finished_at=now,
        duration_s=0.0,
        task=(getattr(args, "prompt", None) or "") or (getattr(args, "task", None) or ""),
        workspace=str(workspace),
        model=getattr(args, "model", None) or getattr(cfg, "model", "") or "",
        profile=getattr(cfg, "profile", "") or "default",
        session_id=None,
        tool_calls=[],
        tokens={"prompt": 0, "completion": 0, "cache_read": 0, "cache_creation": 0},
        cost_est=0.0,
        assistant_text="",
        error=error,
    ).to_json()


def main() -> int:
    # Install the crash-log excepthook FIRST so any uncaught exception
    # during startup (migration, config parse, provider construction,
    # MCP load, gateway spawn) lands in ~/.athena/crashes/ rather than
    # being lost when the operator closes the terminal. Idempotent.
    try:
        from .crash_log import install_excepthook

        install_excepthook()
    except Exception:  # noqa: BLE001
        # The hook is best-effort -- if it can't install, the operator
        # gets the default traceback. Never block startup.
        pass

    # One-time migration of legacy single-profile layout (everything at
    # ~/.athena/<x>) into ~/.athena/profiles/default/<x>. Naturally
    # idempotent — once profiles/ exists, this short-circuits.
    try:
        from .profiles.migration import maybe_run_migration

        maybe_run_migration()
    except Exception as e:  # noqa: BLE001
        # A migration failure must never block startup; the user's
        # legacy items stay in place and the rest of the app still
        # runs. The prior implementation swallowed the exception with
        # an inaccurate "logged in migration.py" comment -- only
        # per-item shutil.move failures actually log inside
        # run_migration; an ImportError on the migration module
        # itself, an ensure_profile failure, or anything in
        # migration_needed flowed through pass with zero indication.
        # Surface a one-liner so the operator at least knows the
        # migration didn't complete and can re-run manually.
        import sys as _sys

        _sys.stderr.write(
            f"warning: legacy-profile migration skipped ({type(e).__name__}: {e}). "
            "Run `athena profiles migrate` to retry.\n"
        )

    # Subcommands short-circuit the interactive parser. argv[1] is the verb.
    if len(sys.argv) >= 2 and sys.argv[1] in _SUBCOMMANDS:
        import importlib

        mod = importlib.import_module(_SUBCOMMANDS[sys.argv[1]])
        return mod.main(sys.argv[2:])

    # T6-07: optional one-line "update available" notice at
    # startup. cfg.update_auto_check defaults to False so
    # this is OFF by default; when on, the lookup has its
    # own 3s timeout so a slow PyPI never blocks the REPL.
    try:
        from .commands.update import startup_notice
        from .config import load_config

        startup_notice(load_config())
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(prog="athena", description="Local Claude Code on Ollama")
    # Distribution name (athena-coder) differs from the Python import
    # name (athena); show both so users hitting --version see the
    # `pip install` identifier alongside the version.
    from . import __version__ as _athena_version

    ap.add_argument(
        "--version",
        action="version",
        version=f"athena-coder {_athena_version}",
    )
    ap.add_argument("-m", "--model", help="Ollama model tag")
    ap.add_argument("-p", "--prompt", help="One-shot prompt; runs and exits")
    ap.add_argument("-C", "--cwd", help="Workspace directory (default: current dir)")
    ap.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip confirmation prompts for tools that opt into them (Bash, etc.)",
    )
    ap.add_argument(
        "--lean-prompt",
        action="store_true",
        help="Use a trimmed system prompt (smaller models, low context)",
    )
    ap.add_argument(
        "--profile",
        help="Active profile name (overrides ATHENA_PROFILE / active_profile / config).",
    )
    # T7-01: headless run primitive flags. Backwards-compatible
    # — existing `athena -p "<task>"` keeps working the same
    # way (status=ok → exit 0). Opt-in via --json for machine-
    # readable output, --timeout for wall-clock cap, --run-id
    # for batch correlation, --task to read the prompt from a
    # file instead of inline.
    ap.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit a structured JSON envelope on stdout (one "
            "line, the full RunResult). Implies -p; routes all "
            "TTY chatter to stderr so stdout stays clean for "
            "downstream parsers."
        ),
    )
    ap.add_argument(
        "--run-id",
        dest="run_id",
        help=(
            "Operator-supplied correlation key for batch / cron "
            "/ eval drivers. Echoed in the JSON envelope. "
            "Auto-minted as r-<uuid12> when absent."
        ),
    )
    ap.add_argument(
        "--timeout",
        type=float,
        help=(
            "Wall-clock timeout in seconds. On expiry, the run "
            "is interrupted, state captured, and the dispatcher "
            "exits 124 (matches timeout(1))."
        ),
    )
    ap.add_argument(
        "--task",
        help=(
            "Path to a file containing the prompt. Alternative "
            "to -p / --prompt for long or shell-unfriendly "
            "task strings."
        ),
    )
    # Rewrite "-foo" -> "--foo" for known long-form flags BEFORE
    # argparse sees argv. Without this, `athena -model NAME` gets
    # parsed as `-m odel NAME` (m's value becomes "odel", NAME lands
    # as an unrecognised positional). This caught a user on the VPS
    # who typed `athena -model anthropic/claude-sonnet-latest`.
    sys.argv = _rewrite_singledash_longs(sys.argv, ap)
    args = ap.parse_args()

    cfg = load_config()
    # Resolve the active profile: CLI > env > active_profile file >
    # config > "default". Apply to cfg so every subsystem that reads
    # cfg.profile (SessionStore root, gateway router, curator state,
    # cron db, gateway routes) lands on the same on-disk root.
    from .profiles.resolution import resolve_active_profile

    cfg.profile = resolve_active_profile(
        cli_arg=args.profile,
        config_default=cfg.profile,
    )
    if args.auto_approve:
        cfg.auto_approve_tools = True
    if args.lean_prompt:
        cfg.lean_prompt = True
    workspace = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()
    if not workspace.is_dir():
        ui.error(f"workspace not a directory: {workspace}")
        return 2

    agent = Agent(cfg, workspace, model=args.model)

    # Load MCP servers — register their tools into the same registry as the
    # built-ins so the model sees one unified tool list.
    def _mcp_log(level: str, msg: str) -> None:
        {"info": ui.info, "warn": ui.warn, "error": ui.error}.get(level, ui.info)(msg)

    try:
        load_mcp_servers(mcp_config_paths(workspace), on_message=_mcp_log)
    except Exception as e:
        ui.error(f"MCP load failed: {e}")

    # Sanity: verify Ollama is reachable
    try:
        models = agent.provider.list_models()
        if not _model_pulled(agent.model, models) and models:
            ui.warn(f"model '{agent.model}' not pulled; available: {', '.join(models[:6])}…")
            ui.warn(f"run:  ollama pull {agent.model}")
    except Exception as e:
        ui.error(f"cannot reach Ollama at {cfg.ollama_host}: {e}")
        ui.warn("start it with `ollama serve` or set OLLAMA_HOST.")
        return 2

    # T7-01: resolve task — inline -p / --prompt OR --task FILE.
    # The two are mutually exclusive; --task wins when both
    # set so a batch driver can override a default at the
    # command line.
    task: str | None = None
    if args.task:
        task_path = Path(args.task)
        if not task_path.exists():
            _err = f"--task file not found: {task_path}"
            if args.json:
                sys.stdout.write(_json_invalid_envelope(_err, args, cfg, workspace) + "\n")
            else:
                ui.error(_err)
            return 2
        try:
            task = task_path.read_text(encoding="utf-8")
        except OSError as e:
            _err = f"--task read failed: {e}"
            if args.json:
                sys.stdout.write(_json_invalid_envelope(_err, args, cfg, workspace) + "\n")
            else:
                ui.error(_err)
            return 2
    elif args.prompt:
        task = args.prompt

    if args.json and not task:
        # --json without -p / --task can't run anything useful.
        _err = "--json requires a task (-p / --prompt or --task FILE)"
        sys.stdout.write(_json_invalid_envelope(_err, args, cfg, workspace) + "\n")
        return 2

    if task is not None:
        # Headless path — wraps the existing one-shot via T7-01's
        # run_headless. JSON mode routes UI chatter to stderr so
        # stdout stays a single clean envelope. Default (non-JSON)
        # mode keeps the existing human-readable behavior.
        from .headless import run_headless

        # UI callback for progress chatter. In JSON mode it goes
        # to stderr so stdout remains parser-friendly.
        if args.json:

            def on_info(m):
                return print(m, file=sys.stderr)
        else:
            on_info = ui.info

        try:
            result = run_headless(
                task=task,
                cfg=cfg,
                workspace=workspace,
                model=args.model,
                run_id=args.run_id,
                timeout_s=args.timeout,
                on_info=on_info,
                agent=agent,
            )
        finally:
            shutdown_all()

        if args.json:
            # Single-line envelope. The contract a batch_runner /
            # cron job / eval harness reads.
            sys.stdout.write(result.to_json() + "\n")
            sys.stdout.flush()
        elif result.status != "ok":
            # Non-JSON path: surface a short status line to
            # stderr on non-success so the human sees what
            # happened. The existing run_turn output already
            # went to stdout during the run.
            ui.error(
                f"run {result.run_id} ended {result.status}"
                + (f": {result.error}" if result.error else "")
            )
        return result.exit_code()

    return _run_interactive_repl(agent, cfg, workspace)


def _run_interactive_repl(agent: Agent, cfg: Any, workspace: Path) -> int:
    """Spawn the Ink TUI, drive the REPL through its gateway.

    All agent output (info / warn / error / tool calls / tool
    results) flows through ``ui.set_gateway()``'s event bridge to
    the Ink subprocess. Slash commands run inline in Python; their
    print output is bridged the same way.

    Falls back to the legacy Rich REPL only when the Ink bundle is
    missing — surfacing a clear message so the user can build it.
    """
    import time as _time

    from .tui_gateway import (
        MessageAppendEvent,
        StatusUpdateEvent,
        TuiGateway,
    )
    from .tui_gateway.banner_data import build_banner
    from .tui_gateway.events import (
        ConfirmReplyCommand,
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
                from .tools import plan as _plan

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
        from .tools import plan as _plan_mod

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
            if not isinstance(cmd, UserInputCommand):
                # Other command types (interrupt) land here;
                # ignore for now.
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
                    if not _handle_slash(agent, line):
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
