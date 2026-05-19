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


SLASH_HELP = """\
/help                show this message
/model NAME          switch model
/models              list available Ollama models
/tools               list registered tools (built-in + MCP)
/mcp                 list connected MCP servers and their tool counts
/mcp logs NAME       show recent stderr from an MCP server
/clear               reset conversation (keeps system prompt)
/cost                show token usage and elapsed time for this session
/save [file]         save transcript (default: ~/.athena/sessions/<timestamp>.json)
/dump                print the current system prompt (what the model sees)
/cwd [path]          show or change workspace
/init                generate ATHENA.md from a workspace survey
/review [ref]        review pending changes (or a git ref)
/security-review     security-focused review of pending changes
/loop INTERVAL CMD   re-run a prompt or slash command on a timer
/loop-stop           stop a running /loop
/compact             summarize history and replace it with the summary
/resume [file]       resume a saved session transcript
/memory [list|show|delete|dir]  inspect or edit persistent memory
/plan [prompt]       enter plan mode (read-only investigation)
/plan-exit           leave plan mode without executing
/steer MSG           queue MSG; delivered before your next prompt
/steer clear         drop every pending steer for this session
/queue               list pending steers
/goal [MSG|show|clear]  set, show, or clear the persistent invariant
/hooks               list configured hooks
/exit                quit
"""


def _slash_help(agent: Agent, arg: str) -> None:
    ui.console.print(SLASH_HELP)


def _slash_model(agent: Agent, arg: str) -> None:
    if not arg:
        ui.info(f"current model: {agent.model}")
    else:
        agent.model = arg.strip()
        ui.info(f"model set to {agent.model}")


def _slash_models(agent: Agent, arg: str) -> None:
    try:
        names = agent.provider.list_models()
    except Exception as e:
        ui.error(f"could not list models: {e}")
        return
    for n in names:
        marker = "*" if n == agent.model else " "
        ui.console.print(f" {marker} {n}")


def _slash_tools(agent: Agent, arg: str) -> None:
    for t in tools.all_tools(disabled=agent.cfg.disabled_tools):
        confirm = " [confirm]" if t.requires_confirmation else ""
        kind = " [mcp]" if "__" in t.name else ""
        ui.console.print(
            f"  • [bold]{t.name}[/]{kind}{confirm} — {t.description.splitlines()[0]}"
        )


def _slash_mcp(agent: Agent, arg: str) -> None:
    sub = arg.split(maxsplit=1)
    clients = active_clients()
    if not sub:
        if not clients:
            ui.info("no MCP servers connected. Drop an mcp.json in the project or ~/.athena/")
            return
        for c in clients:
            status = "alive" if c.is_alive() else "dead"
            tcount = len(c._tools or [])  # safe: list_tools was called at startup
            info = c._server_info.get("serverInfo", {}) if c._server_info else {}
            version = info.get("version", "?")
            ui.console.print(f"  • [bold]{c.name}[/] ({status}, v{version}) — {tcount} tools")
        return
    if sub[0] == "logs":
        if len(sub) < 2:
            ui.error("usage: /mcp logs SERVER")
            return
        target = sub[1].strip()
        client = next((c for c in clients if c.name == target), None)
        if not client:
            ui.error(f"no server named '{target}'")
            return
        lines = client.stderr_tail(50)
        if not lines:
            ui.info(f"({target} has produced no stderr)")
        else:
            for ln in lines:
                ui.console.print(f"  [dim]{ln}[/]")
    else:
        ui.error(f"unknown /mcp subcommand: {sub[0]}")


def _slash_clear(agent: Agent, arg: str) -> None:
    agent.reset()


def _slash_cost(agent: Agent, arg: str) -> None:
    s = agent.stats
    elapsed = time.time() - s.started
    ui.console.print(
        f"turns: {s.turns}  tool calls: {s.tool_calls}\n"
        f"prompt tokens: {s.prompt_tokens}  eval tokens: {s.eval_tokens}\n"
        f"elapsed: {elapsed:.1f}s"
    )


def _slash_status(agent: Agent, arg: str) -> None:
    # `--live` flag (or bare `live` arg) opens the dashboard view;
    # the bare form keeps the snapshot-text behavior so existing
    # users / scripts that grep for the output don't break.
    if arg.strip() in ("live", "--live"):
        ui.live_status(agent)
        return
    from .cli.status import render_status

    snapshot = agent.stats.to_snapshot(
        session_id=agent.session_id,
        model=agent.model,
        provider=getattr(agent.provider, "name", "?"),
        profile=(agent.cfg.profile or "default"),
    )
    ui.console.print(render_status(snapshot))


def _slash_save(agent: Agent, arg: str) -> None:
    path = Path(arg).expanduser() if arg else SESSIONS_DIR / f"{int(time.time())}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agent.messages, indent=2), encoding="utf-8")
    ui.info(f"saved transcript to {path}")


def _slash_dump(agent: Agent, arg: str) -> None:
    sysmsg = next((m for m in agent.messages if m.get("role") == "system"), None)
    if not sysmsg:
        ui.error("no system message in history")
        return
    content = sysmsg.get("content", "")
    ui.info(f"system prompt: {len(content):,} chars / ~{len(content) // 4:,} tokens")
    ui.console.print(content, soft_wrap=True, highlight=False)


def _slash_hooks(agent: Agent, arg: str) -> None:
    from . import hooks as hooks_mod

    hs = hooks_mod.list_hooks()
    if not hs:
        ui.info("no hooks configured. drop one in ~/.athena/settings.json")
        return
    for h in hs:
        ui.console.print(f"  • [bold]{h.event}[/]  matcher={h.matcher!r}  -> {h.command!r}")


def _slash_cwd(agent: Agent, arg: str) -> None:
    if not arg:
        ui.info(f"workspace: {agent.workspace}")
        return
    new = Path(arg).expanduser().resolve()
    if not new.is_dir():
        ui.error(f"not a directory: {new}")
        return
    agent.workspace = new
    tools.file_ops.set_workspace(new, max_read=agent.cfg.max_file_read)
    # Reload hooks for the new workspace, then rebuild the system
    # prompt in place so ATHENA.md / MEMORY.md reflect it. Conversation
    # history is preserved; user can /clear if they want a reset.
    from . import hooks as hooks_mod

    hooks_mod.load_hooks(new)
    if agent.messages and agent.messages[0].get("role") == "system":
        agent.messages[0] = {"role": "system", "content": agent._build_system()}
    ui.info(f"workspace -> {new} (system prompt rebuilt; /clear to reset history)")


# Uniform dispatch table for inline slash commands. New contributors
# find every inline command here in one place; a future move into
# athena/commands/ is now a pure rename per row (Tier-2 follow-up).
_INLINE_SLASH_HANDLERS = {
    "help": _slash_help,
    "model": _slash_model,
    "models": _slash_models,
    "tools": _slash_tools,
    "mcp": _slash_mcp,
    "clear": _slash_clear,
    "cost": _slash_cost,
    "status": _slash_status,
    "save": _slash_save,
    "dump": _slash_dump,
    "hooks": _slash_hooks,
    "cwd": _slash_cwd,
}


def _handle_slash(agent: Agent, line: str) -> bool:
    """Returns True if the loop should continue, False to exit."""
    parts = line[1:].strip().split(maxsplit=1)
    if not parts:
        return True
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("exit", "quit", "q"):
        return False

    handler = _INLINE_SLASH_HANDLERS.get(cmd)
    if handler is not None:
        handler(agent, arg)
        return True

    # Fall through to the commands registry for module-based commands
    # (/compact, /goal, /init, /loop, /memory, /plan, /resume, /review,
    # /steer).
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
