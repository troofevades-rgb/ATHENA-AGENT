"""ACP method handlers."""
from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from athena.acp import capabilities
from athena.acp.methods import _coerce_user_text, register
from athena.acp.server import ACPServer


class _Writer:
    def __init__(self) -> None:
        self.buf = io.StringIO()

    def write(self, s: str) -> int:
        return self.buf.write(s)

    def flush(self) -> None:
        pass

    @property
    def lines(self) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in self.buf.getvalue().splitlines()
            if line.strip()
        ]


class _FakeAgent:
    """Synchronous stub replicating the agent surface methods.py uses."""

    def __init__(
        self, *, response: str = "stub response", session_id: str = "child-1",
    ) -> None:
        self.session_id = session_id
        self.response = response
        self.cancel_pending = False
        self.closed = False
        self.run_calls: list[str] = []
        self._tool_trace: list[dict] = []
        self.goal: str | None = None

    def run_until_done(
        self, user_input: str = "", *, max_iterations: int | None = None,
    ) -> None:
        self.run_calls.append(user_input)

    def last_assistant_message(self) -> str:
        return self.response

    def tool_call_trace(self) -> list[dict]:
        return list(self._tool_trace)

    def close(self) -> None:
        self.closed = True


def _server() -> tuple[ACPServer, _Writer]:
    """Build a server with stub stdin/stdout — no real pipes."""
    reader = asyncio.StreamReader()
    writer = _Writer()
    return ACPServer(stdin=reader, stdout=writer), writer


async def _invoke(
    server: ACPServer, method: str, params: dict | None = None,
) -> dict:
    handler = server._methods[method]
    return await handler(params or {})


# ---- initialize ------------------------------------------------------


async def test_initialize_returns_capabilities() -> None:
    server, _ = _server()
    register(server, agent_factory=_FakeAgent)
    result = await _invoke(server, "initialize")
    assert result["protocol_version"] == capabilities.PROTOCOL_VERSION
    assert result["server_info"] == capabilities.SERVER_INFO
    assert result["capabilities"] == capabilities.CAPABILITIES


# ---- session lifecycle -----------------------------------------------


async def test_session_new_creates_agent_and_returns_id() -> None:
    server, _ = _server()
    sessions = register(server, agent_factory=_FakeAgent)
    result = await _invoke(server, "session/new")
    sid = result["session_id"]
    assert sid.startswith("acp-")
    assert sid in sessions
    assert isinstance(sessions[sid], _FakeAgent)


async def test_session_new_accepts_caller_session_id() -> None:
    server, _ = _server()
    sessions = register(server, agent_factory=_FakeAgent)
    result = await _invoke(
        server, "session/new", {"session_id": "ide-supplied"},
    )
    assert result["session_id"] == "ide-supplied"
    assert "ide-supplied" in sessions


async def test_session_new_idempotent_on_repeat_id() -> None:
    server, _ = _server()
    sessions = register(server, agent_factory=_FakeAgent)
    await _invoke(server, "session/new", {"session_id": "s"})
    first = sessions["s"]
    await _invoke(server, "session/new", {"session_id": "s"})
    assert sessions["s"] is first


async def test_session_end_closes_agent_and_removes() -> None:
    server, _ = _server()
    sessions = register(server, agent_factory=_FakeAgent)
    await _invoke(server, "session/new", {"session_id": "s"})
    result = await _invoke(server, "session/end", {"session_id": "s"})
    assert result["closed"] is True
    assert "s" not in sessions


async def test_session_end_unknown_returns_closed_false() -> None:
    server, _ = _server()
    register(server, agent_factory=_FakeAgent)
    result = await _invoke(server, "session/end", {"session_id": "ghost"})
    assert result["closed"] is False


# ---- send_message --------------------------------------------------


async def test_send_message_runs_agent_and_streams_final(
    capsys: pytest.CaptureFixture,
) -> None:
    server, writer = _server()
    fake = _FakeAgent(response="final answer")
    sessions = register(server, agent_factory=lambda: fake)
    await _invoke(server, "session/new", {"session_id": "s"})
    result = await _invoke(server, "session/send_message", {
        "session_id": "s",
        "message": "do the thing",
    })
    assert result == {"completed": True, "reason": "stop"}
    assert fake.run_calls == ["do the thing"]
    # Stream sequence: turn_started, text_block_start, text_delta,
    # text_block_stop, turn_completed.
    methods = [m["method"] for m in writer.lines]
    assert "session/turn_started" in methods
    assert "session/content_block_start" in methods
    assert "session/content_block_delta" in methods
    assert "session/content_block_stop" in methods
    assert "session/turn_completed" in methods
    # The delta carries the final response.
    deltas = [
        m["params"]["delta"]["text"]
        for m in writer.lines
        if m["method"] == "session/content_block_delta"
    ]
    assert "final answer" in "".join(deltas)


async def test_send_message_unknown_session_returns_error() -> None:
    server, _ = _server()
    register(server, agent_factory=_FakeAgent)
    result = await _invoke(server, "session/send_message", {
        "session_id": "ghost", "message": "hi",
    })
    assert "error" in result and "no such session" in result["error"]


async def test_send_message_agent_exception_surfaces() -> None:
    server, writer = _server()

    class _Crash(_FakeAgent):
        def run_until_done(self, *_a, **_kw):
            raise RuntimeError("simulated crash")

    sessions = register(server, agent_factory=_Crash)
    await _invoke(server, "session/new", {"session_id": "s"})
    result = await _invoke(server, "session/send_message", {
        "session_id": "s", "message": "go",
    })
    assert result["completed"] is False
    assert "simulated crash" in result["error"]
    # turn_completed still fires with reason=error so the IDE clears
    # its spinner.
    completions = [
        m for m in writer.lines if m["method"] == "session/turn_completed"
    ]
    assert completions and completions[0]["params"]["reason"] == "error"


async def test_send_message_surfaces_tool_calls(
    capsys: pytest.CaptureFixture,
) -> None:
    server, writer = _server()
    fake = _FakeAgent()
    fake._tool_trace = [
        {"id": "c-1", "function": {"name": "Bash", "arguments": {"cmd": "ls"}}},
        {"id": "c-2", "function": {"name": "Read", "arguments": {"path": "/x"}}},
    ]
    register(server, agent_factory=lambda: fake)
    await _invoke(server, "session/new", {"session_id": "s"})
    await _invoke(server, "session/send_message", {
        "session_id": "s", "message": "go",
    })
    tool_starts = [
        m for m in writer.lines
        if m["method"] == "session/content_block_start"
        and m["params"]["block"]["type"] == "tool_use"
    ]
    assert len(tool_starts) == 2
    assert {b["params"]["block"]["name"] for b in tool_starts} == {"Bash", "Read"}


async def test_send_message_reports_cancelled_reason_when_flag_set(
    capsys: pytest.CaptureFixture,
) -> None:
    server, writer = _server()
    fake = _FakeAgent()
    fake.cancel_pending = True
    register(server, agent_factory=lambda: fake)
    await _invoke(server, "session/new", {"session_id": "s"})
    result = await _invoke(server, "session/send_message", {
        "session_id": "s", "message": "go",
    })
    assert result["reason"] == "cancelled"


# ---- cancel -------------------------------------------------------


async def test_cancel_sets_flag_on_agent() -> None:
    server, _ = _server()
    sessions = register(server, agent_factory=_FakeAgent)
    await _invoke(server, "session/new", {"session_id": "s"})
    fake = sessions["s"]
    assert fake.cancel_pending is False
    result = await _invoke(server, "session/cancel", {"session_id": "s"})
    assert result == {"cancelled": True}
    assert fake.cancel_pending is True


async def test_cancel_unknown_session_returns_false() -> None:
    server, _ = _server()
    register(server, agent_factory=_FakeAgent)
    result = await _invoke(server, "session/cancel", {"session_id": "ghost"})
    assert result == {"cancelled": False}


# ---- slash command --------------------------------------------------


async def test_slash_command_routed(tmp_path) -> None:
    server, _ = _server()
    register(server, agent_factory=_FakeAgent)
    await _invoke(server, "session/new", {"session_id": "s"})
    result = await _invoke(server, "session/slash_command", {
        "session_id": "s", "command": "steer", "argument": "focus on tests",
    })
    assert "steer queued" in result["result"]


# ---- _coerce_user_text -------------------------------------------


def test_coerce_string_message() -> None:
    assert _coerce_user_text("hi there") == "hi there"


def test_coerce_text_field() -> None:
    assert _coerce_user_text({"text": "hello"}) == "hello"


def test_coerce_content_string() -> None:
    assert _coerce_user_text({"content": "hello"}) == "hello"


def test_coerce_content_blocks() -> None:
    """Anthropic-style content block array."""
    blocks = {
        "content": [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ]
    }
    assert _coerce_user_text(blocks) == "first\nsecond"


def test_coerce_empty_when_nothing_readable() -> None:
    assert _coerce_user_text({}) == ""
    assert _coerce_user_text({"other": "field"}) == ""
    assert _coerce_user_text(None) == ""
    assert _coerce_user_text(42) == ""


def test_coerce_content_blocks_skips_non_text() -> None:
    blocks = {
        "content": [
            {"type": "image", "url": "https://x"},
            {"type": "text", "text": "caption"},
        ]
    }
    assert _coerce_user_text(blocks) == "caption"
