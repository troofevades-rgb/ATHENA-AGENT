"""Integration: tool dispatch stores large results out of band (T2-06.4).

When a tool returns content larger than
``cfg.tool_result_threshold_bytes``, ``Agent._handle_tool_call``
replaces it with the storage handle before recording into history.
Small results pass through unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk
from athena.tools.tool_result_storage import HANDLE_RE


class _ScriptedToolCallProvider:
    """Emits one Read tool_call on the first stream_chat call, then
    a plain final assistant message on the second."""

    name = "scripted-storage"
    requires_api_key = False

    def __init__(self, target_path: str) -> None:
        self._target = target_path
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        if self.calls == 1:
            yield StreamChunk(
                "tool_call",
                {
                    "id": "call_1",
                    "name": "Read",
                    "arguments": f'{{"file_path": "{self._target}"}}',
                },
            )
            yield StreamChunk("end", None)
            return
        yield StreamChunk("content", "done")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["scripted-storage"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def test_large_tool_output_gets_handle(
    isolated_home: Path, workspace: Path, tmp_path: Path, monkeypatch
) -> None:
    """A Read tool returning > threshold bytes lands in conversation
    history as a handle, not as the raw text."""
    monkeypatch.chdir(workspace)

    big_file = workspace / "big.txt"
    # 2 MB of content; raw_threshold default is 1 MB.
    big_file.write_text("x" * 2_000_000, encoding="utf-8")

    provider = _ScriptedToolCallProvider(target_path=big_file.as_posix())
    cfg = Config(
        model="scripted-storage",
        max_turn_steps=4,
        # Use a tiny threshold so the test runs fast.
        tool_result_threshold_bytes=10_000,
        tool_result_storage_path=str(tmp_path / "blobs"),
        # The agent's compressor + cache machinery aren't relevant here.
        context_compress_watermark=10.0,
    )
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("read")

    # Tool-role messages in history; at least one should be a handle.
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert tool_msgs, "no tool-result message recorded"
    contents = [str(m.get("content", "")) for m in tool_msgs]
    assert any(HANDLE_RE.search(c) is not None for c in contents), (
        f"tool result was inlined instead of replaced with a handle; "
        f"contents (first 200 each): {[c[:200] for c in contents]}"
    )

    # And the raw 2 MB content is NOT in any tool message.
    for c in contents:
        assert "xxxxxxxxxxxxxxxxxxxxxxxxx" not in c[:500] or HANDLE_RE.search(c)


def test_small_tool_output_passes_through(
    isolated_home: Path, workspace: Path, tmp_path: Path, monkeypatch
) -> None:
    """A small tool output (< threshold) lands verbatim in history."""
    monkeypatch.chdir(workspace)

    small_file = workspace / "small.txt"
    small_file.write_text("greetings", encoding="utf-8")

    provider = _ScriptedToolCallProvider(target_path=small_file.as_posix())
    cfg = Config(
        model="scripted-storage",
        max_turn_steps=4,
        tool_result_threshold_bytes=1_000_000,
        tool_result_storage_path=str(tmp_path / "blobs"),
        context_compress_watermark=10.0,
    )
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("read")

    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    contents = " ".join(str(m.get("content", "")) for m in tool_msgs)
    # Raw content is present (with line-number prefix from Read).
    assert "greetings" in contents
    # No handle was used.
    assert HANDLE_RE.search(contents) is None
