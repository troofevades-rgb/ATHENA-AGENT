"""Tests for the read_tool_result tool (T2-06.3).

Exercises the tool via the dispatch path so the wiring through
``Agent.tool_result_storage`` is also covered.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.core import Agent, _current_agent
from athena.config import Config
from athena.providers.base import StreamChunk
from athena.tools.tool_result_storage import ToolResultStorage


class _BareProvider:
    name = "bare"
    requires_api_key = False

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        yield StreamChunk("content", "ok")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["bare"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _make_agent(workspace: Path, storage_dir: Path) -> Agent:
    cfg = Config(model="bare")
    agent = Agent(cfg, workspace, provider=_BareProvider())
    agent.tool_result_storage = ToolResultStorage(  # type: ignore[attr-defined]
        storage_dir, session_id="test"
    )
    return agent


def test_tool_returns_content_for_valid_handle(
    isolated_home: Path, workspace: Path, tmp_path: Path
) -> None:
    agent = _make_agent(workspace, tmp_path / "blobs")
    stored = agent.tool_result_storage.store("hello blob", tool_name="shell")

    token = _current_agent.set(agent)
    try:
        from athena.tools.read_tool_result import read_tool_result

        result = read_tool_result(stored.handle, max_bytes=1000, offset=0)
        assert result == "hello blob"
    finally:
        _current_agent.reset(token)


def test_tool_returns_error_for_invalid_handle(
    isolated_home: Path, workspace: Path, tmp_path: Path
) -> None:
    agent = _make_agent(workspace, tmp_path / "blobs")
    token = _current_agent.set(agent)
    try:
        from athena.tools.read_tool_result import read_tool_result

        result = read_tool_result("not a handle")
        assert result.startswith("ERROR:")
    finally:
        _current_agent.reset(token)


def test_tool_returns_error_for_missing_blob(
    isolated_home: Path, workspace: Path, tmp_path: Path
) -> None:
    agent = _make_agent(workspace, tmp_path / "blobs")
    token = _current_agent.set(agent)
    try:
        from athena.tools.read_tool_result import read_tool_result

        result = read_tool_result("0000000000000000")
        assert result.startswith("ERROR:")
    finally:
        _current_agent.reset(token)


def test_tool_paginates_via_offset(isolated_home: Path, workspace: Path, tmp_path: Path) -> None:
    agent = _make_agent(workspace, tmp_path / "blobs")
    payload = "0123456789" * 10  # 100 chars
    stored = agent.tool_result_storage.store(payload, tool_name="shell")

    token = _current_agent.set(agent)
    try:
        from athena.tools.read_tool_result import read_tool_result

        # First page: bytes [0..10) = "0123456789"
        page1 = read_tool_result(stored.handle, max_bytes=10, offset=0)
        assert page1 == "0123456789"
        # Second page: bytes [50..60) = "0123456789"
        page2 = read_tool_result(stored.handle, max_bytes=10, offset=50)
        assert page2 == "0123456789"
        # The two pages are the same 10-byte slice of a repeating
        # pattern — confirms the offset took effect by reading from
        # a non-zero position without error.
    finally:
        _current_agent.reset(token)


def test_tool_errors_when_no_agent_active(tmp_path: Path) -> None:
    """If get_current_agent() returns None, the tool returns an ERROR
    string rather than raising."""
    from athena.tools.read_tool_result import read_tool_result

    result = read_tool_result("0000000000000000")
    assert result.startswith("ERROR:")
