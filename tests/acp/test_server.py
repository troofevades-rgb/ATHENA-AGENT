"""ACPServer — JSON-RPC dispatch + outbound message framing."""
from __future__ import annotations

import asyncio
import io
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from athena.acp.server import (
    ACPError,
    ACPServer,
    ERR_INTERNAL,
    ERR_METHOD_NOT_FOUND,
)


class _StringWriter:
    """Captures writes the way sys.stdout would."""

    def __init__(self) -> None:
        self.buf = io.StringIO()

    def write(self, s: str) -> int:
        return self.buf.write(s)

    def flush(self) -> None:
        pass

    @property
    def lines(self) -> list[dict[str, Any]]:
        """Parse every line written as JSON, drop blanks."""
        return [
            json.loads(line)
            for line in self.buf.getvalue().splitlines()
            if line.strip()
        ]


def _build_server() -> tuple[ACPServer, asyncio.StreamReader, _StringWriter]:
    reader = asyncio.StreamReader()
    writer = _StringWriter()
    return ACPServer(stdin=reader, stdout=writer), reader, writer


def _send(reader: asyncio.StreamReader, obj: dict) -> None:
    """Feed a JSON-RPC message into the server's stdin reader."""
    reader.feed_data((json.dumps(obj) + "\n").encode("utf-8"))


# ---- request handling -----------------------------------------------


async def test_request_routed_to_handler() -> None:
    server, reader, writer = _build_server()

    @server.method("ping")
    async def _ping(params: dict) -> dict:
        return {"pong": True, "echo": params}

    _send(reader, {
        "jsonrpc": "2.0", "id": 1,
        "method": "ping", "params": {"hello": "world"},
    })
    reader.feed_eof()
    await server.serve()

    [msg] = writer.lines
    assert msg["jsonrpc"] == "2.0"
    assert msg["id"] == 1
    assert msg["result"] == {"pong": True, "echo": {"hello": "world"}}


async def test_unknown_method_returns_32601() -> None:
    server, reader, writer = _build_server()
    _send(reader, {"jsonrpc": "2.0", "id": 5, "method": "nonexistent"})
    reader.feed_eof()
    await server.serve()
    [msg] = writer.lines
    assert msg["error"]["code"] == ERR_METHOD_NOT_FOUND
    assert "nonexistent" in msg["error"]["message"]


async def test_handler_exception_returns_32603() -> None:
    server, reader, writer = _build_server()

    @server.method("boom")
    async def _boom(_params: dict) -> None:
        raise RuntimeError("simulated crash")

    _send(reader, {"jsonrpc": "2.0", "id": 7, "method": "boom"})
    reader.feed_eof()
    await server.serve()
    [msg] = writer.lines
    assert msg["error"]["code"] == ERR_INTERNAL
    assert "simulated crash" in msg["error"]["message"]


async def test_handler_acperror_propagates_code() -> None:
    """Handlers can raise ACPError to control the error code."""
    server, reader, writer = _build_server()

    @server.method("validate")
    async def _validate(_params: dict) -> None:
        raise ACPError({"code": -32602, "message": "missing field"})

    _send(reader, {"jsonrpc": "2.0", "id": 1, "method": "validate"})
    reader.feed_eof()
    await server.serve()
    [msg] = writer.lines
    assert msg["error"]["code"] == -32602
    assert msg["error"]["message"] == "missing field"


async def test_handler_returns_none_renders_empty_result() -> None:
    """A handler that returns None should produce result: {} — JSON-RPC
    requires a `result` key when there's no error."""
    server, reader, writer = _build_server()

    @server.method("ack")
    async def _ack(_params: dict) -> None:
        return None

    _send(reader, {"jsonrpc": "2.0", "id": 1, "method": "ack"})
    reader.feed_eof()
    await server.serve()
    [msg] = writer.lines
    assert msg["result"] == {}


# ---- notifications ---------------------------------------------------


async def test_notification_routed_to_handler() -> None:
    server, reader, writer = _build_server()
    seen: list[dict] = []

    @server.notification("ping")
    async def _ping(params: dict) -> None:
        seen.append(params)

    _send(reader, {"jsonrpc": "2.0", "method": "ping", "params": {"x": 1}})
    reader.feed_eof()
    await server.serve()
    assert seen == [{"x": 1}]
    # No response written for notifications.
    assert writer.lines == []


async def test_notification_handler_exception_is_swallowed() -> None:
    server, reader, writer = _build_server()

    @server.notification("noisy")
    async def _noisy(_params: dict) -> None:
        raise RuntimeError("ignored")

    _send(reader, {"jsonrpc": "2.0", "method": "noisy"})
    reader.feed_eof()
    # Must not raise.
    await server.serve()


async def test_unknown_notification_is_silently_ignored() -> None:
    server, reader, writer = _build_server()
    _send(reader, {"jsonrpc": "2.0", "method": "unregistered"})
    reader.feed_eof()
    await server.serve()
    assert writer.lines == []


# ---- malformed input -------------------------------------------------


async def test_malformed_json_line_skipped() -> None:
    server, reader, writer = _build_server()
    reader.feed_data(b"not valid json\n")
    reader.feed_eof()
    await server.serve()
    assert writer.lines == []  # no error response either; just dropped


async def test_message_with_no_method_dropped() -> None:
    server, reader, writer = _build_server()
    _send(reader, {"jsonrpc": "2.0", "id": 1})
    reader.feed_eof()
    await server.serve()
    assert writer.lines == []


async def test_blank_lines_ignored() -> None:
    server, reader, writer = _build_server()
    reader.feed_data(b"\n\n\n")
    reader.feed_eof()
    await server.serve()


# ---- send_notification ----------------------------------------------


async def test_send_notification_serialized_to_stdout() -> None:
    server, reader, writer = _build_server()
    # Run an empty serve in parallel so the stdout-lock event loop
    # is the same one we're notifying from. But for this test we
    # don't need serve — send_notification can be called standalone.
    await server.send_notification(
        "session/content_block_delta",
        {"session_id": "s1", "delta": {"type": "text_delta", "text": "hi"}},
    )
    [msg] = writer.lines
    assert msg["method"] == "session/content_block_delta"
    assert "id" not in msg
    assert msg["params"]["delta"]["text"] == "hi"


async def test_send_notification_locks_stdout() -> None:
    """Two notifications fired concurrently must produce two clean
    lines, not interleaved bytes."""
    server, reader, writer = _build_server()
    await asyncio.gather(
        server.send_notification("a", {"i": 1}),
        server.send_notification("b", {"i": 2}),
        server.send_notification("c", {"i": 3}),
    )
    methods = [m["method"] for m in writer.lines]
    assert set(methods) == {"a", "b", "c"}
    assert len(writer.lines) == 3


# ---- send_request + response routing -------------------------------


async def test_send_request_returns_result_when_response_arrives() -> None:
    server, reader, writer = _build_server()

    async def serve_task() -> None:
        await server.serve()

    asyncio.create_task(serve_task())
    # Submit the request — it writes to stdout. We then simulate the
    # client by feeding a matching response into stdin.
    request_task = asyncio.create_task(
        server.send_request(
            "session/permission_request",
            {"tool_name": "bash"},
            timeout=5.0,
        )
    )
    # Give the request time to write before we feed the response.
    await asyncio.sleep(0.05)
    [request_msg] = writer.lines
    assert request_msg["method"] == "session/permission_request"
    msg_id = request_msg["id"]
    _send(reader, {
        "jsonrpc": "2.0", "id": msg_id,
        "result": {"decision": "allow"},
    })
    result = await asyncio.wait_for(request_task, timeout=5.0)
    assert result == {"decision": "allow"}
    reader.feed_eof()


async def test_send_request_raises_on_error_response() -> None:
    server, reader, writer = _build_server()
    asyncio.create_task(server.serve())
    task = asyncio.create_task(
        server.send_request("any", {}, timeout=5.0)
    )
    await asyncio.sleep(0.05)
    msg_id = writer.lines[0]["id"]
    _send(reader, {
        "jsonrpc": "2.0", "id": msg_id,
        "error": {"code": -32000, "message": "user closed"},
    })
    with pytest.raises(ACPError, match="user closed"):
        await asyncio.wait_for(task, timeout=5.0)
    reader.feed_eof()


async def test_send_request_times_out() -> None:
    server, _reader, _writer = _build_server()
    with pytest.raises(asyncio.TimeoutError):
        await server.send_request("any", {}, timeout=0.05)


async def test_server_shutdown_unblocks_pending_request() -> None:
    """An in-flight client-bound request must surface a clean error
    when stdin EOFs, not hang forever."""
    server, reader, writer = _build_server()

    request_task = asyncio.create_task(
        server.send_request("any", {}, timeout=30.0),
    )
    serve_task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.05)
    reader.feed_eof()
    await asyncio.wait_for(serve_task, timeout=5.0)
    with pytest.raises(ACPError, match="shutting down"):
        await asyncio.wait_for(request_task, timeout=5.0)


async def test_unmatched_response_is_dropped() -> None:
    """A response with an id we never sent — log and move on, no crash."""
    server, reader, writer = _build_server()
    _send(reader, {
        "jsonrpc": "2.0", "id": 99,
        "result": {"unexpected": True},
    })
    reader.feed_eof()
    await server.serve()
    assert writer.lines == []


# ---- concurrency safety --------------------------------------------


async def test_dispatch_is_non_blocking() -> None:
    """A slow handler must not block other dispatches."""
    server, reader, writer = _build_server()
    event = asyncio.Event()

    @server.method("slow")
    async def _slow(_params: dict) -> dict:
        await event.wait()
        return {"ok": True}

    @server.method("fast")
    async def _fast(_params: dict) -> dict:
        return {"ok": True}

    _send(reader, {"jsonrpc": "2.0", "id": 1, "method": "slow"})
    _send(reader, {"jsonrpc": "2.0", "id": 2, "method": "fast"})

    serve_task = asyncio.create_task(server.serve())

    # Wait for the fast one to respond first (even though slow was
    # submitted first), proving dispatch parallelism.
    for _ in range(100):
        if any(m.get("id") == 2 for m in writer.lines):
            break
        await asyncio.sleep(0.01)
    fast_responded = any(m.get("id") == 2 for m in writer.lines)
    slow_responded = any(m.get("id") == 1 for m in writer.lines)
    assert fast_responded
    assert not slow_responded

    # Unblock and clean up.
    event.set()
    reader.feed_eof()
    await asyncio.wait_for(serve_task, timeout=5.0)
