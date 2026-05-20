"""Tests for athena.mcp.transport_stdio (T3-02.9).

Hermetic via io.StringIO substitution — no subprocesses, no real
stdin/stdout.
"""

from __future__ import annotations

import io
import json

from athena.mcp.transport_stdio import run_stdio


def test_stdio_full_handshake_roundtrip(server) -> None:
    requests = [
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"t","version":"1.0"}}}\n',
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n',
        "",  # EOF
    ]
    fake_in = io.StringIO("".join(requests))
    fake_out = io.StringIO()

    run_stdio(server, stdin=fake_in, stdout=fake_out)

    output_lines = [line for line in fake_out.getvalue().splitlines() if line]
    # Two replies: initialize + tools/list. Initialized notification
    # produces no reply.
    assert len(output_lines) == 2

    init_resp = json.loads(output_lines[0])
    assert init_resp["id"] == 1
    assert init_resp["result"]["protocolVersion"] == "2024-11-05"

    tools_resp = json.loads(output_lines[1])
    assert tools_resp["id"] == 2
    assert len(tools_resp["result"]["tools"]) == 7


def test_stdio_malformed_json_returns_parse_error(server) -> None:
    fake_in = io.StringIO('this is not json\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    fake_out = io.StringIO()
    run_stdio(server, stdin=fake_in, stdout=fake_out)
    lines = [line for line in fake_out.getvalue().splitlines() if line]
    # First response is the parse error; second is the ping result.
    parse_err = json.loads(lines[0])
    assert parse_err["error"]["code"] == -32700
    ping_resp = json.loads(lines[1])
    assert ping_resp["id"] == 1
    assert ping_resp["result"] == {}


def test_stdio_eof_exits_cleanly(server) -> None:
    fake_in = io.StringIO("")  # EOF immediately
    fake_out = io.StringIO()
    run_stdio(server, stdin=fake_in, stdout=fake_out)
    # No exception raised; no output.
    assert fake_out.getvalue() == ""


def test_stdio_blank_lines_skipped(server) -> None:
    fake_in = io.StringIO('\n\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n')
    fake_out = io.StringIO()
    run_stdio(server, stdin=fake_in, stdout=fake_out)
    lines = [line for line in fake_out.getvalue().splitlines() if line]
    assert len(lines) == 1
    resp = json.loads(lines[0])
    assert resp["id"] == 1


def test_stdio_notification_produces_no_response(server) -> None:
    fake_in = io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    fake_out = io.StringIO()
    run_stdio(server, stdin=fake_in, stdout=fake_out)
    assert fake_out.getvalue() == ""


def test_stdio_non_object_message_ignored(server) -> None:
    """A JSON message that isn't an object (e.g. a bare number or
    string) is ignored — it can't be a valid JSON-RPC request."""
    fake_in = io.StringIO('42\n"a string"\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    fake_out = io.StringIO()
    run_stdio(server, stdin=fake_in, stdout=fake_out)
    lines = [line for line in fake_out.getvalue().splitlines() if line]
    # Only the ping produced a reply.
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == 1
