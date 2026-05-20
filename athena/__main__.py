"""CLI entry point. Handles argument parsing, REPL, and slash commands."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory

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
}


def main() -> int:
    # One-time migration of legacy single-profile layout (everything at
    # ~/.athena/<x>) into ~/.athena/profiles/default/<x>. Naturally
    # idempotent — once profiles/ exists, this short-circuits.
    try:
        from .profiles.migration import maybe_run_migration

        maybe_run_migration()
    except Exception:
        # A migration failure must never block startup; the user's
        # legacy items stay in place and the rest of the app still
        # runs. Logged in migration.py.
        pass

    # Subcommands short-circuit the interactive parser. argv[1] is the verb.
    if len(sys.argv) >= 2 and sys.argv[1] in _SUBCOMMANDS:
        import importlib

        mod = importlib.import_module(_SUBCOMMANDS[sys.argv[1]])
        return mod.main(sys.argv[2:])

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

    if args.prompt:
        try:
            agent.run_turn(args.prompt)
        finally:
            shutdown_all()
            agent.close()
        return 0

    ui.banner(agent.model, agent.workspace)

    history_file = CONFIG_DIR / "history"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(
        history=FileHistory(str(history_file)),
        # Always-on bottom toolbar shows model · profile · elapsed ·
        # token counters · estimated cost · top-3 tool histogram.
        # The callable re-renders on every redraw so numbers update
        # while the prompt is sitting idle.
        bottom_toolbar=ui.build_bottom_toolbar(agent),
        refresh_interval=1.0,
    )

    try:
        while True:
            try:
                line = session.prompt(HTML('\n<style fg="#00ff00" bold="true">▰▰</style> ')).strip()
            except (EOFError, KeyboardInterrupt):
                ui.console.print()
                break
            if not line:
                continue
            if line.startswith("/"):
                if not _handle_slash(agent, line):
                    break
                continue
            try:
                agent.run_turn(line)
            except KeyboardInterrupt:
                ui.warn("turn interrupted")
                continue
    finally:
        shutdown_all()
        agent.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
