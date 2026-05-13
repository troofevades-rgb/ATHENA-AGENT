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

from . import tools, ui, commands
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
/save [file]         save transcript (default: ~/.ocode/sessions/<timestamp>.json)
/dump                print the current system prompt (what the model sees)
/cwd [path]          show or change workspace
/init                generate OCODE.md from a workspace survey
/review [ref]        review pending changes (or a git ref)
/security-review     security-focused review of pending changes
/loop INTERVAL CMD   re-run a prompt or slash command on a timer
/loop-stop           stop a running /loop
/compact             summarize history and replace it with the summary
/resume [file]       resume a saved session transcript
/memory [list|show|delete|dir]  inspect or edit persistent memory
/plan [prompt]       enter plan mode (read-only investigation)
/plan-exit           leave plan mode without executing
/hooks               list configured hooks
/exit                quit
"""


def _handle_slash(agent: Agent, line: str) -> bool:
    """Returns True if the loop should continue, False to exit."""
    parts = line[1:].strip().split(maxsplit=1)
    if not parts:
        return True
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("exit", "quit", "q"):
        return False

    if cmd == "help":
        ui.console.print(SLASH_HELP)

    elif cmd == "model":
        if not arg:
            ui.info(f"current model: {agent.model}")
        else:
            agent.model = arg.strip()
            ui.info(f"model set to {agent.model}")

    elif cmd == "models":
        try:
            names = agent.client.list_models()
        except Exception as e:
            ui.error(f"could not list models: {e}")
            return True
        for n in names:
            marker = "*" if n == agent.model else " "
            ui.console.print(f" {marker} {n}")

    elif cmd == "tools":
        for t in tools.all_tools(disabled=agent.cfg.disabled_tools):
            confirm = " [confirm]" if t.requires_confirmation else ""
            kind = " [mcp]" if "__" in t.name else ""
            ui.console.print(f"  • [bold]{t.name}[/]{kind}{confirm} — {t.description.splitlines()[0]}")

    elif cmd == "mcp":
        sub = arg.split(maxsplit=1)
        clients = active_clients()
        if not sub:
            if not clients:
                ui.info("no MCP servers connected. Drop an mcp.json in the project or ~/.ocode/")
                return True
            for c in clients:
                status = "alive" if c.is_alive() else "dead"
                tcount = len(c._tools or [])  # safe: list_tools was called at startup
                info = c._server_info.get("serverInfo", {}) if c._server_info else {}
                version = info.get("version", "?")
                ui.console.print(f"  • [bold]{c.name}[/] ({status}, v{version}) — {tcount} tools")
        elif sub[0] == "logs":
            if len(sub) < 2:
                ui.error("usage: /mcp logs SERVER")
                return True
            target = sub[1].strip()
            client = next((c for c in clients if c.name == target), None)
            if not client:
                ui.error(f"no server named '{target}'")
                return True
            lines = client.stderr_tail(50)
            if not lines:
                ui.info(f"({target} has produced no stderr)")
            else:
                for ln in lines:
                    ui.console.print(f"  [dim]{ln}[/]")
        else:
            ui.error(f"unknown /mcp subcommand: {sub[0]}")

    elif cmd == "clear":
        agent.reset()

    elif cmd == "cost":
        s = agent.stats
        elapsed = time.time() - s.started
        ui.console.print(
            f"turns: {s.turns}  tool calls: {s.tool_calls}\n"
            f"prompt tokens: {s.prompt_tokens}  eval tokens: {s.eval_tokens}\n"
            f"elapsed: {elapsed:.1f}s"
        )

    elif cmd == "save":
        path = Path(arg).expanduser() if arg else SESSIONS_DIR / f"{int(time.time())}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(agent.messages, indent=2), encoding="utf-8")
        ui.info(f"saved transcript to {path}")

    elif cmd == "dump":
        sysmsg = next((m for m in agent.messages if m.get("role") == "system"), None)
        if not sysmsg:
            ui.error("no system message in history")
            return True
        content = sysmsg.get("content", "")
        ui.info(f"system prompt: {len(content):,} chars / ~{len(content)//4:,} tokens")
        ui.console.print(content, soft_wrap=True, highlight=False)

    elif cmd == "hooks":
        from . import hooks as hooks_mod
        hs = hooks_mod.list_hooks()
        if not hs:
            ui.info("no hooks configured. drop one in ~/.ocode/settings.json")
            return True
        for h in hs:
            ui.console.print(f"  • [bold]{h.event}[/]  matcher={h.matcher!r}  -> {h.command!r}")

    elif cmd == "cwd":
        if not arg:
            ui.info(f"workspace: {agent.workspace}")
        else:
            new = Path(arg).expanduser().resolve()
            if not new.is_dir():
                ui.error(f"not a directory: {new}")
            else:
                agent.workspace = new
                tools.file_ops.set_workspace(new, max_read=agent.cfg.max_file_read)
                # Reload hooks for the new workspace, then rebuild the system
                # prompt in place so OCODE.md / MEMORY.md reflect it. Conversation
                # history is preserved; user can /clear if they want a reset.
                from . import hooks as hooks_mod
                hooks_mod.load_hooks(new)
                if agent.messages and agent.messages[0].get("role") == "system":
                    agent.messages[0] = {"role": "system", "content": agent._build_system()}
                ui.info(f"workspace -> {new} (system prompt rebuilt; /clear to reset history)")

    else:
        # Fall through to the commands registry
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
    "import-from-hermes": "ocode.cli.import_hermes",
    "reindex": "ocode.cli.reindex",
}


def main() -> int:
    # Subcommands short-circuit the interactive parser. argv[1] is the verb.
    if len(sys.argv) >= 2 and sys.argv[1] in _SUBCOMMANDS:
        import importlib
        mod = importlib.import_module(_SUBCOMMANDS[sys.argv[1]])
        return mod.main(sys.argv[2:])

    ap = argparse.ArgumentParser(prog="ocode", description="Local Claude Code on Ollama")
    ap.add_argument("-m", "--model", help="Ollama model tag")
    ap.add_argument("-p", "--prompt", help="One-shot prompt; runs and exits")
    ap.add_argument("-C", "--cwd", help="Workspace directory (default: current dir)")
    ap.add_argument("--auto-approve", action="store_true", help="Skip confirmation prompts for tools that opt into them (Bash, etc.)")
    ap.add_argument("--lean-prompt", action="store_true", help="Use a trimmed system prompt (smaller models, low context)")
    args = ap.parse_args()

    cfg = load_config()
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
        models = agent.client.list_models()
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
    session = PromptSession(history=FileHistory(str(history_file)))

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
