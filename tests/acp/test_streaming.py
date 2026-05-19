"""StreamingSender + capabilities advertisement."""

from __future__ import annotations

import asyncio
from typing import Any

from athena.acp import capabilities
from athena.acp.streaming import StreamingSender


class _FakeServer:
    """Captures send_notification calls."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, dict[str, Any]]] = []
        self.request_response: Any = {"decision": "allow"}
        self.request_calls: list[tuple[str, dict[str, Any]]] = []
        self.request_raises: Exception | None = None

    async def send_notification(self, method: str, params: dict) -> None:
        self.notifications.append((method, params))

    async def send_request(
        self,
        method: str,
        params: dict,
        *,
        timeout: float = 60.0,
    ) -> Any:
        self.request_calls.append((method, params))
        if self.request_raises:
            raise self.request_raises
        return self.request_response


# ---- text streaming -----------------------------------------------


async def test_text_block_start_emits_content_block_start() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "sess-1")
    await sender.text_block_start("text-0")
    [(method, params)] = server.notifications
    assert method == "session/content_block_start"
    assert params["session_id"] == "sess-1"
    assert params["block"]["type"] == "text"
    assert params["block"]["id"] == "text-0"


async def test_text_delta_emits_content_block_delta() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.text_delta("hello world")
    [(method, params)] = server.notifications
    assert method == "session/content_block_delta"
    assert params["delta"]["type"] == "text_delta"
    assert params["delta"]["text"] == "hello world"
    assert params["block_id"] == "text-0"


async def test_text_delta_empty_string_skipped() -> None:
    """Avoid spamming the IDE with zero-content deltas."""
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.text_delta("")
    assert server.notifications == []


async def test_text_block_stop_emits_content_block_stop() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.text_block_stop()
    [(method, params)] = server.notifications
    assert method == "session/content_block_stop"
    assert params["block_id"] == "text-0"


# ---- tool calls ----------------------------------------------------


async def test_tool_call_start_emits_tool_use_block() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.tool_call_start("call-7", "Bash", {"cmd": "ls -la"})
    [(method, params)] = server.notifications
    assert method == "session/content_block_start"
    block = params["block"]
    assert block["type"] == "tool_use"
    assert block["id"] == "call-7"
    assert block["name"] == "Bash"
    assert block["input"] == {"cmd": "ls -la"}


async def test_tool_call_result_carries_id_and_payload() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.tool_call_result(
        "call-7",
        "total 12\ndrwxr-xr-x ...",
    )
    [(method, params)] = server.notifications
    assert method == "session/tool_result"
    assert params["tool_use_id"] == "call-7"
    assert params["result"].startswith("total 12")
    assert params["is_error"] is False


async def test_tool_call_result_is_error_flag() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.tool_call_result(
        "call-x",
        "permission denied",
        is_error=True,
    )
    _, params = server.notifications[0]
    assert params["is_error"] is True


# ---- permission requests ------------------------------------------


async def test_permission_request_returns_allow() -> None:
    server = _FakeServer()
    server.request_response = {"decision": "allow"}
    sender = StreamingSender(server, "s1")
    decision = await sender.permission_request("Bash", {"cmd": "ls"})
    assert decision == "allow"
    [(method, params)] = server.request_calls
    assert method == "session/permission_request"
    assert params["tool_name"] == "Bash"
    assert params["tool_args"] == {"cmd": "ls"}


async def test_permission_request_returns_deny() -> None:
    server = _FakeServer()
    server.request_response = {"decision": "deny"}
    sender = StreamingSender(server, "s1")
    decision = await sender.permission_request("Write", {})
    assert decision == "deny"


async def test_permission_request_timeout_returns_deny() -> None:
    server = _FakeServer()
    server.request_raises = asyncio.TimeoutError()
    sender = StreamingSender(server, "s1")
    decision = await sender.permission_request("X", {}, timeout=0.01)
    assert decision == "deny"


async def test_permission_request_malformed_response_returns_deny() -> None:
    """Defensive: the IDE might return something unexpected."""
    server = _FakeServer()
    server.request_response = {"unrelated": "field"}
    sender = StreamingSender(server, "s1")
    decision = await sender.permission_request("X", {})
    assert decision == "deny"


async def test_permission_request_unknown_decision_returns_deny() -> None:
    server = _FakeServer()
    server.request_response = {"decision": "maybe"}
    sender = StreamingSender(server, "s1")
    decision = await sender.permission_request("X", {})
    assert decision == "deny"


async def test_permission_request_exception_returns_deny() -> None:
    """Any error from the bridge — IDE crashed mid-request, etc. —
    must surface as deny so the tool gets safely blocked."""
    server = _FakeServer()
    server.request_raises = RuntimeError("ide disconnected")
    sender = StreamingSender(server, "s1")
    decision = await sender.permission_request("X", {})
    assert decision == "deny"


# ---- turn lifecycle ----------------------------------------------


async def test_turn_started_notification() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.turn_started()
    [(method, params)] = server.notifications
    assert method == "session/turn_started"
    assert params["session_id"] == "s1"


async def test_turn_completed_with_reason() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.turn_completed(reason="cancelled")
    [(method, params)] = server.notifications
    assert method == "session/turn_completed"
    assert params["reason"] == "cancelled"


async def test_turn_completed_default_reason() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "s1")
    await sender.turn_completed()
    _, params = server.notifications[0]
    assert params["reason"] == "stop"


# ---- session_id propagation through everything --------------------


async def test_every_notification_carries_session_id() -> None:
    server = _FakeServer()
    sender = StreamingSender(server, "the-specific-session")
    await sender.text_block_start()
    await sender.text_delta("hi")
    await sender.text_block_stop()
    await sender.tool_call_start("t", "Bash", {})
    await sender.tool_call_result("t", "ok")
    await sender.turn_started()
    await sender.turn_completed()
    for _method, params in server.notifications:
        assert params["session_id"] == "the-specific-session"


# ---- capabilities table -----------------------------------------


def test_capabilities_table_has_required_keys() -> None:
    """The IDE handshake needs these exact keys; check we advertise
    all of them."""
    required = {
        "streaming",
        "tools",
        "approvals",
        "file_attachments",
        "slash_commands",
        "models_listing",
        "session_lifecycle",
    }
    assert required.issubset(capabilities.CAPABILITIES.keys())


def test_capabilities_all_bools() -> None:
    for key, value in capabilities.CAPABILITIES.items():
        assert isinstance(value, bool), f"{key}: {type(value)}"


def test_server_info_has_name_and_version() -> None:
    assert "name" in capabilities.SERVER_INFO
    assert "version" in capabilities.SERVER_INFO
    assert capabilities.SERVER_INFO["name"] == "athena"


def test_protocol_version_string() -> None:
    assert isinstance(capabilities.PROTOCOL_VERSION, str)
