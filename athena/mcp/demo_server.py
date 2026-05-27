"""Minimal self-contained MCP server, stdlib only.

Exists for two reasons:
  1. Integration test: lets us verify athena's MCP client works end-to-end
     without depending on npm / uvx / a network connection.
  2. Reference: ~120 lines of Python show exactly what an MCP server needs
     to do. Copy and modify.

Tools exposed:
  echo(text)              - returns text back
  add(a, b)               - returns a + b
  current_time()          - returns ISO-8601 now()

Run standalone:
    python -m athena.mcp.demo_server
(speaks JSON-RPC on stdin/stdout)
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


def _log_call(name: Any, args: dict[str, Any], result: str, is_error: bool) -> None:
    """Append one ``{tool, args, result, is_error}`` JSON line to
    the file pointed at by ``$ATHENA_EVAL_MCP_LOG`` if that env var
    is set. Used by the agent-eval harness to verify the agent called
    the right tools with the right args; no-op in normal use. Best
    effort — failures here must NOT interrupt the MCP protocol."""
    log_path = os.environ.get("ATHENA_EVAL_MCP_LOG")
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "tool": name,
                "args": args,
                "result": result,
                "is_error": is_error,
            }) + "\n")
    except OSError:
        pass

TOOLS = [
    {
        "name": "echo",
        "description": "Echo the provided text back unchanged. Useful for connectivity tests.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "Return the sum of two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "current_time",
        "description": "Return the current local time as an ISO-8601 string.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _send(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _result(req_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _text_content(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _handle(msg: dict[str, Any]) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    # Notifications have no id; ignore.
    if req_id is None:
        return

    if method == "initialize":
        _result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "athena-demo", "version": "0.1.0"},
            },
        )
    elif method == "tools/list":
        _result(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        result_text: str = ""
        is_error = False
        try:
            if name == "echo":
                result_text = str(args.get("text", ""))
            elif name == "add":
                result_text = str(float(args["a"]) + float(args["b"]))
            elif name == "current_time":
                result_text = datetime.datetime.now().isoformat(timespec="seconds")
            else:
                result_text = f"unknown tool: {name}"
                is_error = True
        except (KeyError, TypeError, ValueError) as e:
            result_text = f"bad arguments: {e}"
            is_error = True
        _log_call(name, args, result_text, is_error)
        _result(req_id, _text_content(result_text, is_error=is_error))
    else:
        _error(req_id, -32601, f"method not found: {method}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            _handle(msg)
        except Exception as e:  # last-ditch — never let the loop die silently
            print(f"demo_server internal error: {e}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
