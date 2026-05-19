"""``athena acp {serve, install-zed}``.

``serve`` is the actual ACP entry — Zed (and other ACP-speaking
IDEs) spawn ``athena acp serve`` as a subprocess, talk to it via
stdin/stdout, and read diagnostics from stderr. Everything else
(session lifecycle, streaming, approvals, slash commands) is set up
by :func:`athena.acp.methods.register`; this CLI just wires the
agent factory to current cfg + workspace and kicks the server.

``install-zed`` prints a snippet for the user to drop into their
Zed ``settings.json``. There's no automated install — Zed's config
file lives outside athena's control and writing to it without
explicit user action would be presumptuous.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("athena.acp.cli")


# ---- subcommand: serve ----------------------------------------------


async def _serve_async(profile: str | None) -> int:
    from ..acp.methods import register
    from ..acp.server import ACPServer
    from ..config import load_config

    cfg = load_config()
    if profile:
        cfg.profile = profile

    workspace = Path.cwd()

    def _factory():
        # Defer the import so we don't construct an agent (and pull
        # in providers / skills / etc.) unless the IDE actually calls
        # session/new.
        from ..agent.core import Agent

        return Agent(cfg, workspace, model=cfg.model)

    server = ACPServer()
    sessions = register(server, agent_factory=_factory)

    # Log diagnostics to stderr only — the protocol uses stdout.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "athena acp serve up (profile=%s, workspace=%s)",
        cfg.profile,
        workspace,
    )
    try:
        await server.serve()
    finally:
        # Close every session on shutdown so any owned provider
        # client lets go cleanly.
        for sid, agent in list(sessions.items()):
            try:
                close = getattr(agent, "close", None)
                if close is not None:
                    close()
            except Exception:
                logger.debug("agent.close failed for %s", sid, exc_info=True)
            sessions.pop(sid, None)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        return asyncio.run(_serve_async(args.profile))
    except KeyboardInterrupt:
        return 0


# ---- subcommand: install-zed ---------------------------------------


def cmd_install_zed(args: argparse.Namespace) -> int:
    """Print the Zed ``agent_servers`` snippet for the user to copy
    into ``~/.config/zed/settings.json`` (Linux/macOS) or
    ``%APPDATA%\\Zed\\settings.json`` (Windows).

    We don't write the file ourselves; Zed's settings.json is the
    user's domain and merging into it would risk clobbering custom
    configuration. Print + instruct.
    """
    snippet = {
        "agent_servers": {
            "athena": {
                "command": "athena",
                "args": ["acp", "serve"],
                "env": {},
            }
        }
    }
    if args.json:
        sys.stdout.write(json.dumps(snippet, indent=2) + "\n")
        return 0

    sys.stdout.write("Add the following to your Zed settings.json:\n\n")
    sys.stdout.write(json.dumps(snippet, indent=2) + "\n\n")
    sys.stdout.write(
        "Settings path:\n"
        "  Linux/macOS: ~/.config/zed/settings.json\n"
        "  Windows:     %APPDATA%\\Zed\\settings.json\n"
        "\n"
        "After saving, restart Zed and open the Agent panel to use athena.\n"
    )
    return 0


# ---- argument parser ----------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena acp")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser(
        "serve",
        help="Run the ACP JSON-RPC server over stdio (called by the IDE).",
    )
    p_serve.add_argument(
        "--profile",
        help="Profile name (default: from config / ATHENA_PROFILE).",
    )
    p_serve.set_defaults(handler=cmd_serve)

    p_zed = sub.add_parser(
        "install-zed",
        help="Print the Zed settings.json snippet to enable athena as an agent server.",
    )
    p_zed.add_argument(
        "--json",
        action="store_true",
        help="Emit just the JSON snippet (no instructions).",
    )
    p_zed.set_defaults(handler=cmd_install_zed)

    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
