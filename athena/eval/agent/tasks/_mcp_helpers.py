"""Helpers for MCP-bucket tasks.

The eval treats MCP tasks like every other task — setup_fn populates
the workspace, the agent runs, verify_fn inspects results. The only
addition: setup_fn writes a ``workspace/mcp.json`` pointing at an
in-tree mock server, and the agent's MCP loader picks it up when
the Agent is built in that workspace.

Two server templates are available:

  ``demo`` (``athena.mcp.demo_server``) — already in tree;
                                          echo/add/current_time
  ``users`` (``mock_users_server.py``)  — written here; get_user/
                                          list_users with a small
                                          fixture dataset

Both servers log every tool call to a JSONL in the workspace
(``mcp_call_log.jsonl``) so the verifier has machine-readable
ground truth. The runner exposes the parsed log via
``ctx.mcp_call_log`` automatically when the MCP-helper-built
servers are attached.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


_CALL_LOG_FILE = "mcp_call_log.jsonl"


def write_workspace_mcp_config(
    workspace: Path,
    servers: dict[str, dict[str, Any]],
) -> None:
    """Write ``workspace/mcp.json`` so the agent's MCP loader picks
    up these mock servers when it boots in that workspace.

    ``servers`` maps server name → entry shape:
      ``{"command": ..., "args": [...], "env": {...}, "cwd": ...}``
    """
    path = workspace / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": servers}, indent=2),
        encoding="utf-8",
    )


def demo_server_config(workspace: Path) -> dict[str, Any]:
    """Spawn the in-tree ``athena.mcp.demo_server`` (echo/add/current_time).

    The server is athena's reference MCP implementation — sturdy and
    doesn't depend on npm/uvx. Logs every call to the workspace's
    ``mcp_call_log.jsonl`` via the ``ATHENA_EVAL_MCP_LOG`` env var.
    """
    return {
        "command": sys.executable,
        "args": ["-m", "athena.mcp.demo_server"],
        "env": {
            "ATHENA_EVAL_MCP_LOG": str(workspace / _CALL_LOG_FILE),
        },
    }


def mock_users_server_config(workspace: Path) -> dict[str, Any]:
    """Spawn the ``mock_users_server.py`` shipped next to this module.

    Tools:
      - ``get_user(id: str)`` → returns ``{"id", "name", "email"}``
        for a small fixture set (ids 1-5); returns ``{"error": ...}``
        otherwise.
      - ``list_users()``      → returns the full fixture list.
    """
    server_path = Path(__file__).resolve().parent / "mock_users_server.py"
    return {
        "command": sys.executable,
        "args": [str(server_path)],
        "env": {
            "ATHENA_EVAL_MCP_LOG": str(workspace / _CALL_LOG_FILE),
        },
    }


def read_call_log(workspace: Path) -> list[dict[str, Any]]:
    """Parse the call log emitted by the mock servers.

    Each line is ``{tool, args, result}``. Missing file → empty list
    (treat as "no MCP calls happened" — the task probably failed
    upstream before any tool fired)."""
    path = workspace / _CALL_LOG_FILE
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def find_call(
    log: list[dict[str, Any]],
    *,
    tool: str,
    arg_match: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the first call to ``tool`` whose args MATCH ``arg_match``
    (subset match, case-insensitive for string values). ``None`` if
    no match."""
    for entry in log:
        if entry.get("tool") != tool:
            continue
        if arg_match is None:
            return entry
        args = entry.get("args") or {}
        ok = True
        for k, expected in arg_match.items():
            actual = args.get(k)
            if isinstance(expected, str) and isinstance(actual, str):
                if expected.lower() != actual.lower():
                    ok = False
                    break
            elif expected != actual:
                ok = False
                break
        if ok:
            return entry
    return None
