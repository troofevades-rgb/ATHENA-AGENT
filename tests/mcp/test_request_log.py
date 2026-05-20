"""Tests for athena.mcp.request_log (T3-02 audit)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from athena.mcp.request_log import (
    McpRequestLog,
    summarise_params,
    summarise_result,
)
from athena.mcp.resources import AthenaMCPResources
from athena.mcp.server import AthenaMCPServer
from athena.mcp.tools import AthenaMCPTools
from athena.safety.snapshots import SnapshotStore


def test_record_writes_jsonl(tmp_path) -> None:
    log_path = tmp_path / "mcp.jsonl"
    rlog = McpRequestLog(log_path=log_path)
    rlog.record(
        request_id="1",
        client_name="claude-desktop",
        method="tools/list",
        params_summary={},
        result_summary={"tool_count": 7},
        latency_ms=12.5,
    )
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["request_id"] == "1"
    assert entry["client_name"] == "claude-desktop"
    assert entry["method"] == "tools/list"
    assert entry["latency_ms"] == 12.5
    assert entry["result_summary"] == {"tool_count": 7}


def test_record_with_error(tmp_path) -> None:
    log_path = tmp_path / "mcp.jsonl"
    rlog = McpRequestLog(log_path=log_path)
    rlog.record(
        request_id="2",
        client_name="x",
        method="bogus",
        params_summary=None,
        result_summary=None,
        latency_ms=1,
        error={"code": -32601, "message": "method not found: bogus"},
    )
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert "error" in entry
    assert entry["error"]["code"] == -32601


def test_multiple_lines_append(tmp_path) -> None:
    log_path = tmp_path / "mcp.jsonl"
    rlog = McpRequestLog(log_path=log_path)
    for i in range(3):
        rlog.record(
            request_id=str(i),
            client_name="x",
            method="ping",
            params_summary={},
            result_summary={},
            latency_ms=1,
        )
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 3


def test_summarise_params_initialize_pulls_client_info() -> None:
    s = summarise_params(
        "initialize",
        {"clientInfo": {"name": "claude-desktop", "version": "0.7.0"}},
    )
    assert s == {"client_name": "claude-desktop", "client_version": "0.7.0"}


def test_summarise_params_tools_call_pulls_tool_name() -> None:
    s = summarise_params(
        "tools/call",
        {"name": "athena_list_skills", "arguments": {"include_archived": False}},
    )
    assert s == {"tool_name": "athena_list_skills", "arg_count": 1}


def test_summarise_params_resources_read_pulls_uri() -> None:
    s = summarise_params("resources/read", {"uri": "athena://skills/foo"})
    assert s == {"uri": "athena://skills/foo"}


def test_summarise_params_other_returns_empty() -> None:
    assert summarise_params("ping", {}) == {}


def test_summarise_result_tools_list_counts_tools() -> None:
    s = summarise_result("tools/list", {"tools": [1, 2, 3, 4, 5, 6, 7]})
    assert s == {"tool_count": 7}


def test_summarise_result_tools_call_counts_body_bytes() -> None:
    s = summarise_result(
        "tools/call",
        {
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "text", "text": "world"},
            ]
        },
    )
    assert s == {"content_blocks": 2, "body_bytes": 10, "is_error": False}


def test_summarise_result_tools_call_flags_error() -> None:
    s = summarise_result(
        "tools/call",
        {"content": [{"type": "text", "text": "ouch"}], "isError": True},
    )
    assert s["is_error"] is True


def test_summarise_result_resources_read_counts_blocks() -> None:
    s = summarise_result(
        "resources/read",
        {"contents": [{"uri": "athena://skills/x", "text": "body"}]},
    )
    assert s == {"content_blocks": 1, "body_bytes": 4}


# ---------------------------------------------------------------------------
# End-to-end through the server
# ---------------------------------------------------------------------------


def _build_server(tmp_path: Path) -> tuple[AthenaMCPServer, Path]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    profile = tmp_path / "profile"
    profile.mkdir()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    snapshot_store = SnapshotStore(root=tmp_path / "snapshots", relative_to=tmp_path)
    tools = AthenaMCPTools(
        workspace=workspace,
        memory_profile="default",
        audit_dir=audit_dir,
        snapshot_store=snapshot_store,
    )
    resources = AthenaMCPResources(
        workspace=workspace,
        memory_profile="default",
        audit_dir=audit_dir,
    )
    log_path = tmp_path / "mcp.jsonl"
    server = AthenaMCPServer(
        tools=tools,
        resources=resources,
        request_log=McpRequestLog(log_path=log_path),
    )
    return server, log_path


def test_server_logs_each_request(tmp_path) -> None:
    server, log_path = _build_server(tmp_path)
    # Initialize first so the client name lands.
    server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test-client", "version": "1.0"}},
        }
    )
    server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "athena_list_skills", "arguments": {}},
        }
    )
    # Add a tiny sleep so latency_ms is non-zero on fast machines.
    time.sleep(0.001)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    entries = [json.loads(ln) for ln in lines]
    assert entries[0]["method"] == "initialize"
    assert entries[0]["params_summary"]["client_name"] == "test-client"
    assert entries[1]["method"] == "tools/list"
    assert entries[1]["result_summary"]["tool_count"] == 7
    # Client name was captured from initialize and carries forward.
    assert entries[1]["client_name"] == "test-client"
    assert entries[2]["method"] == "tools/call"
    assert entries[2]["params_summary"]["tool_name"] == "athena_list_skills"


def test_server_logs_errors(tmp_path) -> None:
    server, log_path = _build_server(tmp_path)
    server.handle_request({"jsonrpc": "2.0", "id": 5, "method": "definitely_not_a_method"})
    entries = [json.loads(ln) for ln in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert "error" in entries[0]
    assert entries[0]["error"]["code"] == -32601


def test_notifications_not_logged(tmp_path) -> None:
    """Notifications don't get a response and don't get a log line
    either — there's nothing for a reviewer to correlate against."""
    server, log_path = _build_server(tmp_path)
    server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert not log_path.exists()
