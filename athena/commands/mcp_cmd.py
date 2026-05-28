"""``/mcp`` — list connected MCP servers.

``/mcp`` alone shows every connected server with its alive/dead
status, version, and tool count. ``/mcp logs NAME`` tails the
most recent stderr from one server (useful for debugging a
misbehaving subprocess).
"""

from __future__ import annotations

from .. import ui
from ..mcp.loader import active_clients, disable_server, enable_server, hidden_servers
from . import command


@command("mcp")
def cmd_mcp(agent, arg: str = "") -> str:
    sub = arg.split(maxsplit=1)
    clients = active_clients()
    hidden = hidden_servers()
    if not sub:
        if not clients:
            ui.info("no MCP servers connected. Drop an mcp.json in the project or ~/.athena/")
            return ""
        for c in clients:
            status = "alive" if c.is_alive() else "dead"
            tcount = len(c._tools or [])
            info = c._server_info.get("serverInfo", {}) if c._server_info else {}
            version = info.get("version", "?")
            vis = " [dim](hidden)[/]" if c.name in hidden else ""
            ui.console.print(f"  • [bold]{c.name}[/] ({status}, v{version}) — {tcount} tools{vis}")
        return ""
    verb = sub[0]
    if verb == "enable":
        if len(sub) < 2:
            ui.error("usage: /mcp enable SERVER")
            return ""
        target = sub[1].strip()
        if not any(c.name == target for c in clients):
            ui.error(f"no server named '{target}'")
            return ""
        if enable_server(target):
            ui.info(f"'{target}' tools are now visible to the model")
        else:
            ui.info(f"'{target}' is already enabled")
        return ""
    if verb == "disable":
        if len(sub) < 2:
            ui.error("usage: /mcp disable SERVER")
            return ""
        target = sub[1].strip()
        if not any(c.name == target for c in clients):
            ui.error(f"no server named '{target}'")
            return ""
        if disable_server(target):
            ui.info(f"'{target}' tools are now hidden from the model")
        else:
            ui.info(f"'{target}' is already disabled")
        return ""
    if verb == "logs":
        if len(sub) < 2:
            ui.error("usage: /mcp logs SERVER")
            return ""
        target = sub[1].strip()
        client = next((c for c in clients if c.name == target), None)
        if not client:
            ui.error(f"no server named '{target}'")
            return ""
        lines = client.stderr_tail(50)
        if not lines:
            ui.info(f"({target} has produced no stderr)")
        else:
            for ln in lines:
                ui.console.print(f"  [dim]{ln}[/]")
        return ""
    ui.error(f"unknown /mcp subcommand: {sub[0]}")
    return ""
