"""Mock MCP server: user-record lookup tools.

Companion to ``athena.mcp.demo_server`` for the agent-eval's MCP
bucket. Follows the same minimal stdio JSON-RPC pattern; tools:

  - ``get_user(id: str)``  → ``{"id", "name", "email"}`` for the
                              fixture id, or ``{"error": "..."}``.
  - ``list_users()``       → JSON array of all fixture users.

Logs every tool call to ``$ATHENA_EVAL_MCP_LOG`` (one JSON line per
call) when that env var is set, so the eval verifier has machine-
readable ground truth on what the agent actually called.

Run standalone:
    python -m athena.eval.agent.tasks.mock_users_server
(speaks JSON-RPC on stdin/stdout)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


FIXTURES: dict[str, dict[str, str]] = {
    "1": {"id": "1", "name": "Ada Lovelace", "email": "ada@analytical.eng"},
    "2": {"id": "2", "name": "Grace Hopper", "email": "grace@navy.mil"},
    "3": {"id": "3", "name": "Linus Torvalds", "email": "linus@kernel.org"},
    "4": {"id": "4", "name": "Margaret Hamilton", "email": "margaret@apollo.gov"},
    "5": {"id": "5", "name": "Donald Knuth", "email": "knuth@stanford.edu"},
}


TOOLS = [
    {
        "name": "get_user",
        "description": (
            "Fetch a single user record by id. Returns JSON with "
            "id, name, and email fields. Returns an error if the id "
            "isn't in the fixture set."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "list_users",
        "description": "List every user in the fixture set.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _send(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _result(req_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
    )


def _text_content(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _log_call(name: Any, args: dict[str, Any], result: str, is_error: bool) -> None:
    log_path = os.environ.get("ATHENA_EVAL_MCP_LOG")
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "tool": name,
                        "args": args,
                        "result": result,
                        "is_error": is_error,
                    }
                )
                + "\n"
            )
    except OSError:
        pass


def _handle(msg: dict[str, Any]) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if req_id is None:
        return

    if method == "initialize":
        _result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mock-users", "version": "0.1.0"},
            },
        )
    elif method == "tools/list":
        _result(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        result_text: str = ""
        is_error = False
        if name == "get_user":
            uid = str(args.get("id", ""))
            if uid in FIXTURES:
                result_text = json.dumps(FIXTURES[uid])
            else:
                result_text = json.dumps({"error": f"no user with id {uid!r}"})
                is_error = True
        elif name == "list_users":
            result_text = json.dumps(list(FIXTURES.values()))
        else:
            result_text = f"unknown tool: {name}"
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
        except Exception as e:  # noqa: BLE001
            req_id = msg.get("id") if isinstance(msg, dict) else None
            if req_id is not None:
                _error(req_id, -32000, f"server error: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
