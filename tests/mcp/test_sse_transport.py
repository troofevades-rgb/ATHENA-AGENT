"""SSETransport — HTTP/SSE MCP transport with OAuth.

The transport runs an event loop on a daemon thread; tests drive
it via a small asyncio stub server that speaks the legacy MCP SSE
protocol (``GET /sse`` with an ``event: endpoint`` first frame +
JSON-RPC frames in ``data:`` lines; ``POST /messages``).

Using a real HTTP server instead of respx because we exercise the
full bytes-on-the-wire path including SSE frame boundaries —
mocking that with respx would re-implement the parser we're testing.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from athena.mcp import oauth
from athena.mcp.sse_transport import SSEError, SSETransport

# ---- stub SSE server -------------------------------------------------


class _StubSSEServer:
    """Minimal SSE-speaking HTTP server bound to 127.0.0.1.

    Speaks just enough of the MCP SSE protocol to drive the transport:
    a ``GET /sse`` returns an event: endpoint then waits for a queue
    of frames the test pushes; ``POST /messages`` records the body
    and the test can decide whether to push a response back.
    """

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.event_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.sse_status = 200
        self.post_status = 200
        self.post_response_body = ""
        self.connections_accepted = 0
        self._server: asyncio.base_events.Server | None = None
        self._port: int | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle,
            "127.0.0.1",
            0,
        )
        socket = self._server.sockets[0]
        self._port = socket.getsockname()[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            parts = request_line.decode("latin-1").split(" ")
            method, path = parts[0], parts[1] if len(parts) > 1 else ""

            # Drain headers + body.
            content_length = 0
            while True:
                header = await reader.readline()
                if header in (b"\r\n", b""):
                    break
                if header.lower().startswith(b"content-length:"):
                    content_length = int(header.split(b":")[1].strip())
            body = await reader.read(content_length) if content_length > 0 else b""

            if method == "GET" and path.startswith("/sse"):
                self.connections_accepted += 1
                await self._serve_sse(writer)
            elif method == "POST" and path.startswith("/messages"):
                try:
                    self.posts.append(json.loads(body) if body else {})
                except json.JSONDecodeError:
                    self.posts.append({"_raw": body.decode("latin-1")})
                resp_body = self.post_response_body.encode() if self.post_response_body else b"{}"
                writer.write(
                    f"HTTP/1.1 {self.post_status} OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(resp_body)}\r\n"
                    "Connection: close\r\n\r\n".encode()
                )
                writer.write(resp_body)
                await writer.drain()
            else:
                writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
                await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _serve_sse(self, writer: asyncio.StreamWriter) -> None:
        if self.sse_status != 200:
            writer.write(
                f"HTTP/1.1 {self.sse_status} Unauthorized\r\nContent-Length: 0\r\n\r\n".encode()
            )
            await writer.drain()
            return
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n\r\n"
        )
        await writer.drain()
        try:
            while True:
                chunk = await self.event_queue.get()
                if chunk is None:  # sentinel: close stream
                    break
                writer.write(chunk)
                await writer.drain()
        except Exception:
            pass

    # ---- test helpers ----

    def push_endpoint(self, endpoint: str = "/messages?sessionId=abc") -> None:
        frame = f"event: endpoint\ndata: {endpoint}\n\n".encode()
        self.event_queue.put_nowait(frame)

    def push_jsonrpc(self, message: dict) -> None:
        frame = f"data: {json.dumps(message)}\n\n".encode()
        self.event_queue.put_nowait(frame)


@pytest.fixture
async def stub_server() -> _StubSSEServer:
    """A fresh SSE stub for each test."""
    server = _StubSSEServer()
    await server.start()
    yield server
    await server.stop()


# ---- frame parsing (no transport thread) -----------------------------


def test_handle_frame_endpoint_sets_post_url(tmp_path: Path) -> None:
    """We can test the frame handler directly by patching the transport
    to avoid network in __init__."""
    # Construct without going through __init__ to avoid the loop spin-up.
    t = SSETransport.__new__(SSETransport)
    t.name = "test"
    t._endpoint_ready = threading.Event()
    t._post_endpoint = "/messages"
    t._pending = {}
    t._handle_frame("endpoint", "/messages?sessionId=abc123")
    assert t._post_endpoint == "/messages?sessionId=abc123"
    assert t._endpoint_ready.is_set()


def test_handle_frame_dispatches_to_pending_future() -> None:
    t = SSETransport.__new__(SSETransport)
    t.name = "test"
    t._endpoint_ready = threading.Event()
    t._post_endpoint = "/messages"
    t._pending = {}
    loop = asyncio.new_event_loop()
    try:
        fut: asyncio.Future = loop.create_future()
        t._pending[7] = fut
        t._handle_frame(
            "message",
            '{"jsonrpc":"2.0","id":7,"result":{"ok":true}}',
        )
        assert fut.done()
        assert fut.result()["result"] == {"ok": True}
        assert 7 not in t._pending
    finally:
        loop.close()


def test_handle_frame_ignores_unknown_id() -> None:
    """A JSON-RPC response for an id we don't know is just dropped."""
    t = SSETransport.__new__(SSETransport)
    t.name = "test"
    t._endpoint_ready = threading.Event()
    t._post_endpoint = "/messages"
    t._pending = {}
    # Should not raise.
    t._handle_frame(
        "message",
        '{"jsonrpc":"2.0","id":99,"result":{}}',
    )


def test_handle_frame_silently_skips_malformed_json() -> None:
    t = SSETransport.__new__(SSETransport)
    t.name = "test"
    t._endpoint_ready = threading.Event()
    t._post_endpoint = "/messages"
    t._pending = {}
    # No exception.
    t._handle_frame("message", "{not json")


# ---- end-to-end with stub server ------------------------------------


async def test_open_waits_for_endpoint_event(stub_server: _StubSSEServer) -> None:
    """Constructor blocks until the endpoint event lands (or default
    fallback after timeout)."""
    stub_server.push_endpoint("/messages?sessionId=xyz")

    transport = await asyncio.to_thread(
        lambda: SSETransport(
            "test",
            stub_server.base_url,
            open_timeout=3.0,
        )
    )
    try:
        # Give the listener a tick to consume the endpoint event.
        await asyncio.sleep(0.1)
        assert transport._post_endpoint == "/messages?sessionId=xyz"
    finally:
        await asyncio.to_thread(transport.close)


async def test_request_round_trip_via_sse_response(
    stub_server: _StubSSEServer,
) -> None:
    """Client POSTs a JSON-RPC request; stub sends the response back
    via the SSE stream; client's request() unblocks with the result."""
    stub_server.push_endpoint()

    transport = await asyncio.to_thread(
        lambda: SSETransport(
            "test",
            stub_server.base_url,
            open_timeout=3.0,
        )
    )
    try:
        await asyncio.sleep(0.1)

        # Run request() on a thread because it's sync; meanwhile
        # we'll push the SSE response.
        result_holder: dict = {}

        def worker():
            result_holder["r"] = transport.request(
                "echo",
                {"hello": "world"},
                timeout=5.0,
            )

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        # Wait until the POST shows up so we know which id to respond to.
        for _ in range(50):
            if stub_server.posts:
                break
            await asyncio.sleep(0.02)
        assert stub_server.posts, "POST was never received by stub"
        msg_id = stub_server.posts[0]["id"]
        stub_server.push_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"echoed": True},
            }
        )
        await asyncio.to_thread(t.join, 5.0)
    finally:
        await asyncio.to_thread(transport.close)
    assert result_holder.get("r") == {"echoed": True}


async def test_list_tools_calls_request(stub_server: _StubSSEServer) -> None:
    stub_server.push_endpoint()
    transport = await asyncio.to_thread(
        lambda: SSETransport("test", stub_server.base_url, open_timeout=3.0)
    )
    try:
        await asyncio.sleep(0.1)
        result_holder: dict = {}

        def worker():
            result_holder["r"] = transport.list_tools()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        for _ in range(50):
            if stub_server.posts:
                break
            await asyncio.sleep(0.02)
        msg_id = stub_server.posts[0]["id"]
        assert stub_server.posts[0]["method"] == "tools/list"
        stub_server.push_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": [{"name": "a"}, {"name": "b"}]},
            }
        )
        await asyncio.to_thread(t.join, 5.0)
    finally:
        await asyncio.to_thread(transport.close)
    assert result_holder["r"] == [{"name": "a"}, {"name": "b"}]


async def test_call_tool_envelope_shape(
    stub_server: _StubSSEServer,
) -> None:
    stub_server.push_endpoint()
    transport = await asyncio.to_thread(
        lambda: SSETransport("test", stub_server.base_url, open_timeout=3.0)
    )
    try:
        await asyncio.sleep(0.1)
        result_holder: dict = {}

        def worker():
            result_holder["r"] = transport.call_tool("Bash", {"cmd": "ls"})

        threading.Thread(target=worker, daemon=True).start()
        for _ in range(50):
            if stub_server.posts:
                break
            await asyncio.sleep(0.02)
        envelope = stub_server.posts[0]
        assert envelope["method"] == "tools/call"
        assert envelope["params"] == {"name": "Bash", "arguments": {"cmd": "ls"}}
        stub_server.push_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": envelope["id"],
                "result": {"content": "ok"},
            }
        )
        await asyncio.sleep(0.2)
    finally:
        await asyncio.to_thread(transport.close)


async def test_error_response_raises(stub_server: _StubSSEServer) -> None:
    stub_server.push_endpoint()
    transport = await asyncio.to_thread(
        lambda: SSETransport("test", stub_server.base_url, open_timeout=3.0)
    )
    try:
        await asyncio.sleep(0.1)
        err_holder: dict = {}

        def worker():
            try:
                transport.request("explode", {}, timeout=5.0)
            except SSEError as e:
                err_holder["e"] = str(e)

        threading.Thread(target=worker, daemon=True).start()
        for _ in range(50):
            if stub_server.posts:
                break
            await asyncio.sleep(0.02)
        stub_server.push_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": stub_server.posts[0]["id"],
                "error": {"code": -32000, "message": "bad"},
            }
        )
        for _ in range(50):
            if "e" in err_holder:
                break
            await asyncio.sleep(0.02)
    finally:
        await asyncio.to_thread(transport.close)
    assert "bad" in err_holder["e"]


async def test_close_unblocks_pending_requests(
    stub_server: _StubSSEServer,
) -> None:
    """If close() runs while a request is in flight, the request must
    bail with an SSEError rather than hang forever."""
    stub_server.push_endpoint()
    transport = await asyncio.to_thread(
        lambda: SSETransport("test", stub_server.base_url, open_timeout=3.0)
    )
    await asyncio.sleep(0.1)
    err_holder: dict = {}

    def worker():
        try:
            transport.request("never-replies", timeout=5.0)
        except SSEError as e:
            err_holder["e"] = str(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # Let the POST land so the future is registered.
    for _ in range(50):
        if stub_server.posts:
            break
        await asyncio.sleep(0.02)
    # Now close — the pending future must resolve with an SSEError.
    await asyncio.to_thread(transport.close)
    await asyncio.to_thread(t.join, 5.0)
    assert "closed" in err_holder["e"]


# ---- construction / timeout edge cases ------------------------------


def test_construct_requires_base_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SSETransport("test", base_url="")


# ---- auth header building ------------------------------------------


def test_auth_headers_includes_bearer_when_token_present() -> None:
    t = SSETransport.__new__(SSETransport)
    t._token = oauth.StoredToken(
        access_token="AT-1",
        refresh_token="RT",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        token_type="Bearer",
    )
    headers = t._auth_headers()
    assert headers["Authorization"] == "Bearer AT-1"
    assert "text/event-stream" in headers["Accept"]


def test_auth_headers_no_authorization_when_no_token() -> None:
    t = SSETransport.__new__(SSETransport)
    t._token = None
    headers = t._auth_headers()
    assert "Authorization" not in headers


# ---- request id allocation ----------------------------------------


async def test_request_after_close_raises(stub_server: _StubSSEServer) -> None:
    """A closed transport must refuse new requests cleanly."""
    stub_server.push_endpoint()
    transport = await asyncio.to_thread(
        lambda: SSETransport("test", stub_server.base_url, open_timeout=3.0)
    )
    await asyncio.sleep(0.1)
    await asyncio.to_thread(transport.close)
    with pytest.raises(SSEError, match="closed"):
        transport.request("any")
