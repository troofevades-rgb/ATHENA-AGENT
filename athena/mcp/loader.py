"""MCP config loader and tool-registration glue.

Config schema (compatible with Claude Desktop / Claude Code):

    {
      "mcpServers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/some/path"],
          "env": {"DEBUG": "1"},
          "cwd": "/optional/working/dir",
          "disabled": false,
          "allowed_tools": ["read_file"],     // athena extension: whitelist
          "disabled_tools": ["write_file"]    // athena extension: blacklist
        }
      }
    }

The `allowed_tools` / `disabled_tools` extensions let you trim what gets
exposed to the model — useful when you want a server's read tools but not
its write tools, or to prune for context-window pressure.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..tools.registry import _REGISTRY, Tool  # internal: we register Tool objects directly
from .client import MCPError, format_tool_result
from .transport_resolver import MCPTransport, open_transport

# Anything the resolver returns — stdio or SSE — looks the same here:
# both expose initialize / list_tools / call_tool / close.
_ACTIVE_CLIENTS: list[MCPTransport] = []


def load_mcp_servers(
    config_paths: list[Path],
    on_message: Callable[[str, str], None] | None = None,
) -> list[MCPTransport]:
    """Read configs, spawn each server, register its tools.

    config_paths: list of files to read in order; later overrides earlier.
    on_message: optional callback(level, msg) for status output (level in
                {"info", "warn", "error"}). If None, falls back to print.

    Returns the list of started clients. Failures on individual servers are
    logged but don't abort startup of the others.
    """
    log = on_message or (lambda level, msg: print(f"[{level}] {msg}"))

    merged: dict[str, dict[str, Any]] = {}
    for p in config_paths:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log("error", f"failed to parse {p}: {e}")
            continue
        servers = data.get("mcpServers") or {}
        if not isinstance(servers, dict):
            log("error", f"{p}: 'mcpServers' must be an object")
            continue
        merged.update(servers)

    if not merged:
        return []

    started: list[MCPTransport] = []
    for name, scfg in merged.items():
        if not isinstance(scfg, dict):
            log("error", f"server '{name}': config must be an object")
            continue
        if scfg.get("disabled"):
            log("info", f"mcp server '{name}': disabled, skipping")
            continue

        client: MCPTransport | None = None
        try:
            client = open_transport(name, scfg)
            client.initialize()
            tools = client.list_tools()
        except ValueError as e:
            # Bad config (unknown transport, missing required field).
            log("error", f"mcp server '{name}': {e}")
            continue
        except MCPError as e:
            log("error", f"mcp server '{name}' failed to start: {e}")
            if client is not None:
                client.close()
            continue
        except Exception as e:
            log("error", f"mcp server '{name}' unexpected error: {e}")
            if client is not None:
                client.close()
            continue

        allowed = set(scfg.get("allowed_tools") or [])
        denied = set(scfg.get("disabled_tools") or [])
        registered = 0
        for tdef in tools:
            tname = tdef.get("name")
            if not tname:
                continue
            if allowed and tname not in allowed:
                continue
            if tname in denied:
                continue
            _register_mcp_tool(name, client, tdef, log)
            registered += 1
        log("info", f"mcp server '{name}': {registered}/{len(tools)} tools registered")
        started.append(client)

    _ACTIVE_CLIENTS.extend(started)
    return started


def _register_mcp_tool(
    server_name: str,
    client: MCPTransport,
    tool_def: dict[str, Any],
    log: Callable[[str, str], None],
) -> None:
    """Register one MCP tool into athena's tool registry under '{server}__{tool}'."""
    raw_name = tool_def["name"]
    full_name = f"{server_name}__{raw_name}"
    description = (
        tool_def.get("description") or f"(MCP tool '{raw_name}' from server '{server_name}')"
    )
    schema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}

    if full_name in _REGISTRY:
        log("warn", f"mcp tool name collision: '{full_name}' already registered, overwriting")

    # Capture client + raw_name in a closure that ignores Python kwarg checking
    # (we can't introspect the schema reliably enough to make a real signature).
    def _dispatcher(**kwargs: Any) -> str:
        result = client.call_tool(raw_name, kwargs)
        return format_tool_result(result)

    # Bypass introspection in registry.dispatch by accepting **kwargs
    _dispatcher.__name__ = full_name
    _dispatcher.__qualname__ = full_name

    _REGISTRY[full_name] = Tool(
        name=full_name,
        description=description,
        parameters=schema,
        func=_dispatcher,
        # Most MCP tools that mutate something don't self-identify; we don't
        # block them with confirmation by default. Use disabled_tools or the
        # `--auto-approve` flag is irrelevant here. Per-tool confirmation
        # would need an annotation we don't have today.
        requires_confirmation=False,
    )


def shutdown_all() -> None:
    """Close every running MCP server. Safe to call multiple times."""
    while _ACTIVE_CLIENTS:
        client = _ACTIVE_CLIENTS.pop()
        try:
            client.close()
        except Exception:
            pass


def active_clients() -> list[MCPTransport]:
    return list(_ACTIVE_CLIENTS)
