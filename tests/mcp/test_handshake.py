"""Tests for athena.mcp.server handshake + dispatch (T3-02.7)."""

from __future__ import annotations


def test_initialize_returns_protocol_version_and_capabilities(server) -> None:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
    )
    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    result = response["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert "tools" in result["capabilities"]
    assert "resources" in result["capabilities"]
    # We do NOT advertise prompts or sampling.
    assert "prompts" not in result["capabilities"]
    assert "sampling" not in result["capabilities"]
    assert result["serverInfo"]["name"] == "athena-mcp-server"


def test_initialized_notification_sets_state_and_returns_none(server) -> None:
    # Notifications have no `id`.
    response = server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response is None
    assert server._initialized is True


def test_unknown_method_returns_method_not_found(server) -> None:
    response = server.handle_request({"jsonrpc": "2.0", "id": 5, "method": "completely_made_up"})
    assert response is not None
    assert response["error"]["code"] == -32601
    assert "completely_made_up" in response["error"]["message"]


def test_unknown_notification_silently_dropped(server) -> None:
    response = server.handle_request(
        {"jsonrpc": "2.0", "method": "notifications/something_unknown"}
    )
    assert response is None


def test_tools_list_returns_seven_descriptors(server) -> None:
    response = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = response["result"]["tools"]
    names = sorted(t["name"] for t in tools)
    assert names == [
        "athena_audit_query",
        "athena_list_memories",
        "athena_list_skills",
        "athena_read_memory",
        "athena_read_skill",
        "athena_rollback_files",
        "athena_snapshot_files",
    ]


def test_resources_list_returns_descriptors(server) -> None:
    response = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    resources = response["result"]["resources"]
    uris = sorted(r["uri"] for r in resources)
    assert "athena://skills/" in uris
    assert "athena://memories/" in uris
    assert "athena://audit/" in uris


def test_ping_returns_empty_result(server) -> None:
    response = server.handle_request({"jsonrpc": "2.0", "id": 99, "method": "ping"})
    assert response["id"] == 99
    assert response["result"] == {}


def test_tools_call_with_invalid_arguments_returns_invalid_params(server) -> None:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "athena_list_skills", "arguments": "not-an-object"},
        }
    )
    assert response["error"]["code"] == -32602


def test_handler_exception_returns_internal_error(server, monkeypatch) -> None:
    """An unexpected exception inside a handler surfaces as -32603."""

    def _boom(*_a, **_kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(server.tools, "call_tool", _boom)
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "athena_list_skills", "arguments": {}},
        }
    )
    assert response["error"]["code"] == -32603
    assert "kaboom" in response["error"]["message"]
