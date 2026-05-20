"""Stdio transport: line-delimited JSON-RPC over stdin/stdout (T3-02.5).

Each MCP message is one line of JSON on stdin; each response is one
line of JSON on stdout. EOF on stdin = clean exit. Logs go to
stderr because stdout *is the wire* — printing logs to stdout would
corrupt the JSON-RPC stream.

Sync rather than asyncio because:

- The demo server (:mod:`athena.mcp.demo_server`) proves sync stdlib
  works.
- Athena's tool surface is sync (StreamChunk iterators, file ops,
  snapshot/audit access).
- Stdio is line-by-line request/response; there's no concurrent
  work to overlap.

The asyncio dance the spec suggested (``loop.run_in_executor`` on
``sys.stdin.readline``) buys us nothing here.
"""

from __future__ import annotations

import io
import json
import logging
import sys
from typing import IO

from .server import AthenaMCPServer

logger = logging.getLogger(__name__)


def run_stdio(
    server: AthenaMCPServer,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> None:
    """Pump JSON-RPC messages between ``stdin`` and ``stdout`` until EOF.

    ``stdin`` / ``stdout`` default to ``sys.stdin`` / ``sys.stdout``;
    tests inject ``io.StringIO`` to assert on the produced output
    without launching a subprocess.
    """
    in_stream: IO[str] = stdin if stdin is not None else sys.stdin
    out_stream: IO[str] = stdout if stdout is not None else sys.stdout

    while True:
        line = in_stream.readline()
        if not line:
            logger.info("MCP stdio: EOF on stdin; exiting")
            return
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            # Per JSON-RPC, malformed JSON gets an error response with
            # id=null. The client may choose to give up or retry.
            logger.warning("MCP stdio: malformed JSON on line: %s", e)
            _write_response(
                out_stream,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"parse error: {e}"},
                },
            )
            continue

        if not isinstance(req, dict):
            logger.warning("MCP stdio: non-object message ignored: %r", req)
            continue

        response = server.handle_request(req)
        if response is None:
            continue  # notification — no reply
        _write_response(out_stream, response)


def _write_response(out_stream: IO[str], payload: dict) -> None:
    """One-line compact JSON + newline + flush. Stdout buffering eats
    replies in some environments (Windows console with line-buffered
    stdio is the usual offender), so flush is non-optional here."""
    out_stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    # StringIO doesn't have .flush in some test setups; guard.
    try:
        out_stream.flush()
    except (AttributeError, io.UnsupportedOperation):
        pass
