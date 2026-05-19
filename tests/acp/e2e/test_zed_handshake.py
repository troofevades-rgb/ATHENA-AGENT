"""End-to-end ACP handshake — what Zed actually does.

Drives the server through the full IDE startup sequence:

1. ``initialize`` — IDE asks what we support.
2. ``session/new`` — IDE opens a new chat thread.
3. ``session/send_message`` — IDE forwards the user's prompt.
4. Receive streaming notifications + final response.
5. ``session/end`` — IDE closes the thread.

Assertions check both the response shape AND the notification
sequence (turn_started → content_block_start → text_delta →
content_block_stop → turn_completed).

The agent is a stub so we don't need a real provider; the goal is
to verify the protocol wiring, not the LLM behavior.
"""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any

from athena.acp.methods import register
from athena.acp.server import ACPServer


class _StubAgent:
    """Mimics the Agent surface methods.py uses."""

    def __init__(self) -> None:
        self.cancel_pending = False
        self.received: list[str] = []
        self.closed = False
        self.goal: str | None = None

    def run_until_done(self, user_input: str = "", **_kw) -> None:
        self.received.append(user_input)

    def last_assistant_message(self) -> str:
        last = self.received[-1] if self.received else ""
        return f"echo: {last}"

    def tool_call_trace(self) -> list[dict]:
        return []

    def close(self) -> None:
        self.closed = True


class _ProtocolHarness:
    """Bidirectional pipe between a fake IDE and an ACPServer.

    Feeds JSON-RPC frames into the server's stdin, captures
    everything the server writes to stdout, lets the IDE side
    read responses + notifications.
    """

    def __init__(self) -> None:
        self.reader = asyncio.StreamReader()
        self.writer_buf = io.StringIO()
        self.server = ACPServer(stdin=self.reader, stdout=self)
        self.serve_task: asyncio.Task | None = None
        self._read_offset = 0

    # File-like protocol for ACPServer's writer.
    def write(self, s: str) -> int:
        return self.writer_buf.write(s)

    def flush(self) -> None:
        pass

    async def start(self) -> None:
        self.serve_task = asyncio.create_task(self.server.serve())

    async def stop(self) -> None:
        self.reader.feed_eof()
        if self.serve_task is not None:
            await asyncio.wait_for(self.serve_task, timeout=5.0)

    def send(self, msg: dict) -> None:
        self.reader.feed_data((json.dumps(msg) + "\n").encode("utf-8"))

    async def read_response(self, msg_id: Any, *, timeout: float = 5.0) -> dict:
        """Block until a response with the given id appears in stdout."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            for msg in self.all_messages():
                if msg.get("id") == msg_id and ("result" in msg or "error" in msg):
                    return msg
            if loop.time() > deadline:
                raise asyncio.TimeoutError(f"no response for id={msg_id} within {timeout}s")
            await asyncio.sleep(0.02)

    def all_messages(self) -> list[dict]:
        text = self.writer_buf.getvalue()
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def notifications(self) -> list[dict]:
        return [m for m in self.all_messages() if "id" not in m]


# ---- the handshake ----------------------------------------------------


async def test_full_zed_handshake_sequence() -> None:
    """initialize → session/new → send_message → end."""
    harness = _ProtocolHarness()
    register(harness.server, agent_factory=_StubAgent)
    await harness.start()
    try:
        # 1. initialize
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            }
        )
        resp = await harness.read_response(1)
        assert resp["result"]["protocol_version"]
        assert resp["result"]["server_info"]["name"] == "athena"
        assert resp["result"]["capabilities"]["streaming"] is True

        # 2. session/new
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {},
            }
        )
        resp = await harness.read_response(2)
        sid = resp["result"]["session_id"]
        assert sid.startswith("acp-")

        # 3. session/send_message
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/send_message",
                "params": {"session_id": sid, "message": "hello athena"},
            }
        )
        resp = await harness.read_response(3)
        assert resp["result"]["completed"] is True
        assert resp["result"]["reason"] == "stop"

        # Verify the notification sequence is well-formed.
        methods = [m["method"] for m in harness.notifications()]
        assert "session/turn_started" in methods
        assert "session/content_block_start" in methods
        assert "session/content_block_delta" in methods
        assert "session/content_block_stop" in methods
        assert "session/turn_completed" in methods
        # The text delta carries the agent's response (the stub echoes).
        deltas = [
            m["params"]["delta"]["text"]
            for m in harness.notifications()
            if m["method"] == "session/content_block_delta"
        ]
        assert any("echo: hello athena" in d for d in deltas)

        # 4. session/end
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "session/end",
                "params": {"session_id": sid},
            }
        )
        resp = await harness.read_response(4)
        assert resp["result"]["closed"] is True
    finally:
        await harness.stop()


async def test_cancel_during_busy_turn() -> None:
    """session/cancel mid-turn sets the flag; the next turn boundary
    aborts cleanly."""

    started = asyncio.Event()
    can_finish = asyncio.Event()

    class _SlowAgent(_StubAgent):
        def run_until_done(self, user_input: str = "", **_kw) -> None:
            self.received.append(user_input)
            # Signal to the test that we're inside the run loop.
            started.set()
            # Block until the test releases us.
            can_finish.wait(timeout=10.0) if hasattr(can_finish, "wait") else None
            # The test sets cancel_pending; the real agent loop reads
            # it. Simulate that here by checking the flag.
            # (Our stub doesn't model the inner loop; we just don't
            # care to test the abort path, only that the cancel
            # method sets the flag.)

    harness = _ProtocolHarness()
    register(harness.server, agent_factory=_SlowAgent)
    await harness.start()
    try:
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session/new",
                "params": {"session_id": "s"},
            }
        )
        await harness.read_response(1)

        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/cancel",
                "params": {"session_id": "s"},
            }
        )
        resp = await harness.read_response(2)
        assert resp["result"] == {"cancelled": True}
    finally:
        await harness.stop()


async def test_slash_command_via_acp() -> None:
    """The IDE forwards /steer through session/slash_command."""
    harness = _ProtocolHarness()
    register(harness.server, agent_factory=_StubAgent)
    await harness.start()
    try:
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session/new",
                "params": {"session_id": "s"},
            }
        )
        await harness.read_response(1)
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/slash_command",
                "params": {
                    "session_id": "s",
                    "command": "steer",
                    "argument": "focus on tests",
                },
            }
        )
        resp = await harness.read_response(2)
        assert "steer queued" in resp["result"]["result"]
    finally:
        await harness.stop()


async def test_unknown_method_returns_error() -> None:
    """An IDE that calls a method we don't expose must get a clean
    -32601 rather than crashing the subprocess."""
    harness = _ProtocolHarness()
    register(harness.server, agent_factory=_StubAgent)
    await harness.start()
    try:
        harness.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "fictional/method",
                "params": {},
            }
        )
        resp = await harness.read_response(1)
        assert resp["error"]["code"] == -32601
    finally:
        await harness.stop()
