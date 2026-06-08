"""CLI entry point. Handles argument parsing, REPL, and slash commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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
    for action in parser._actions:
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


# _handle_slash and _run_interactive_repl moved to athena/cli/repl.py
# (consolidation pass 2026-06-01). Both names remain importable from
# here as backwards-compat re-exports for one release; new code
# should import from athena.cli.repl directly.
from .cli.repl import _handle_slash, _run_interactive_repl  # noqa: E402, F401

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


def _force_utf8_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8.

    On Windows the console defaults to a legacy code page (cp1252/cp437),
    so any non-ASCII output athena prints itself — the owl banner, box-
    drawing, em dashes, a model name with accents — raises
    ``UnicodeEncodeError`` or renders as ``?``. Reconfiguring the Python
    streams to UTF-8 fixes the encoding half (the terminal still needs a
    UTF-8-capable font/profile for glyphs). No-op on already-UTF-8
    platforms; best-effort and never fatal.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def main() -> int:
    _force_utf8_streams()
    from .boot_trace import cp as _cp

    _cp("main_entry", argv=sys.argv[1:])
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
    _cp("excepthook_installed")

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
        return cast(int, mod.main(sys.argv[2:]))

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

    ap = argparse.ArgumentParser(prog="athena", description="Local first Agentic CLI")
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
    _cp("pre_agent_init", workspace=str(workspace), model=args.model or cfg.model)

    agent = Agent(cfg, workspace, model=args.model)
    _cp("post_agent_init", session_id=getattr(agent, "session_id", None))

    # Load MCP servers — register their tools into the same registry as the
    # built-ins so the model sees one unified tool list.
    def _mcp_log(level: str, msg: str) -> None:
        {"info": ui.info, "warn": ui.warn, "error": ui.error}.get(level, ui.info)(msg)

    _cp("pre_mcp_load")
    try:
        load_mcp_servers(
            mcp_config_paths(workspace),
            on_message=_mcp_log,
            default_timeout=float(getattr(cfg, "mcp_startup_timeout", 10.0)),
        )
    except Exception as e:
        ui.error(f"MCP load failed: {e}")
        _cp("mcp_load_exception", exc=f"{type(e).__name__}: {e}")
    _cp("post_mcp_load")

    # Sanity: verify Ollama is reachable
    _cp("pre_ollama_check")
    try:
        models = agent.provider.list_models()
        if not _model_pulled(agent.model, models) and models:
            ui.warn(f"model '{agent.model}' not pulled; available: {', '.join(models[:6])}…")
            ui.warn(f"run:  ollama pull {agent.model}")
    except Exception as e:
        ui.error(f"cannot reach Ollama at {cfg.ollama_host}: {e}")
        ui.warn("start it with `ollama serve` or set OLLAMA_HOST.")
        _cp("ollama_unreachable", exc=f"{type(e).__name__}: {e}")
        return 2
    _cp("post_ollama_check")

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
        _cp("pre_headless")
        # Headless path — wraps the existing one-shot via T7-01's
        # run_headless. JSON mode routes UI chatter to stderr so
        # stdout stays a single clean envelope. Default (non-JSON)
        # mode keeps the existing human-readable behavior.
        from .headless import run_headless

        # UI callback for progress chatter. In JSON mode it goes
        # to stderr so stdout remains parser-friendly.
        on_info: Callable[[str], None]
        if args.json:

            def on_info(m: str) -> None:
                print(m, file=sys.stderr)
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
        _cp("post_headless", status=str(result.status), exit_code=result.exit_code())
        return result.exit_code()

    # Belt + suspenders: register terminal-restore at atexit BEFORE
    # the REPL spawns the TUI so any crash path (uncaught exception
    # mid-turn, signal-driven termination, etc.) still resets the
    # alt-screen / cursor / SGR state before PowerShell takes over.
    # Without this, a hard-killed TUI leaves the terminal in
    # alt-screen mode and the user sees a "frozen" window. Idempotent:
    # the helper writes mode-setting (not state-toggling) ANSI codes
    # so a duplicate call from gateway.close() and from atexit is
    # safe.
    import atexit

    from .tui_gateway.server import _restore_terminal

    atexit.register(_restore_terminal)
    _cp("pre_repl")
    _rc = _run_interactive_repl(agent, cfg, workspace)
    _cp("post_repl", rc=_rc)
    return _rc


if __name__ == "__main__":
    sys.exit(main())
