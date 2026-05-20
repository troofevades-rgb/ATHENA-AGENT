"""Integration: tool dispatch routes args through schema_sanitizer
before json.loads (T2-05.3).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk


class _ScriptedToolCallProvider:
    """Yields a tool_call with a specified args payload, then a stop.

    The tool call hits the Read tool (works on a file we'll create
    inside the workspace), so a successful sanitised parse causes the
    Read to execute and surface a usage chunk in the next round.
    """

    name = "scripted-tools"
    requires_api_key = False

    def __init__(self, args_raw: str, target_file: str = "hello.txt") -> None:
        self._args_raw = args_raw
        self._target_file = target_file
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        if self.calls == 1:
            # Emit a tool_call chunk; args_raw is whatever shape the
            # test wants to feed through the sanitiser.
            yield StreamChunk(
                "tool_call",
                {"id": "call_1", "name": "Read", "arguments": self._args_raw},
            )
            yield StreamChunk("end", None)
            return
        # Second call (after tool result returns): emit a final assistant
        # message so the loop exits.
        yield StreamChunk("content", "done")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["scripted-tools"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _make_agent(workspace: Path, provider: Any) -> Agent:
    cfg = Config(model="scripted-tools", max_turn_steps=4)
    return Agent(cfg, workspace, provider=provider)


def test_dispatch_recovers_unquoted_keys(isolated_home: Path, workspace: Path) -> None:
    """A tool_call whose arguments string has unquoted keys parses
    cleanly via the sanitiser and the tool actually runs."""
    target = workspace / "hello.txt"
    target.write_text("greetings", encoding="utf-8")

    # Args with unquoted key — invalid JSON, but the sanitiser
    # quotes the key.
    args_raw = f'{{file_path: "{target.as_posix()}"}}'
    provider = _ScriptedToolCallProvider(args_raw, target_file=str(target))
    agent = _make_agent(workspace, provider)

    agent.run_turn("read hello")

    # Find the tool-result message in history. Look for "greetings"
    # in any tool message content (Read prepends line numbers).
    tool_results = [m for m in agent.messages if m.get("role") == "tool"]
    assert tool_results, "no tool-result message in history"
    combined = " ".join(str(m.get("content", "")) for m in tool_results)
    assert "greetings" in combined


def test_dispatch_recovers_trailing_comma(isolated_home: Path, workspace: Path) -> None:
    """A tool_call with a trailing comma in args parses via sanitiser."""
    target = workspace / "hello.txt"
    target.write_text("greetings", encoding="utf-8")

    args_raw = f'{{"file_path": "{target.as_posix()}",}}'
    provider = _ScriptedToolCallProvider(args_raw)
    agent = _make_agent(workspace, provider)

    agent.run_turn("read")

    tool_results = [m for m in agent.messages if m.get("role") == "tool"]
    combined = " ".join(str(m.get("content", "")) for m in tool_results)
    assert "greetings" in combined


def test_dispatch_sanitize_disabled_falls_through(isolated_home: Path, workspace: Path) -> None:
    """With tool_call_sanitize=False, malformed args parse to {} (the
    existing fallback), so Read is called with no args and surfaces
    its own error rather than the sanitiser's recovery."""
    target = workspace / "hello.txt"
    target.write_text("greetings", encoding="utf-8")

    args_raw = f'{{file_path: "{target.as_posix()}"}}'  # unquoted key
    provider = _ScriptedToolCallProvider(args_raw)
    cfg = Config(model="scripted-tools", max_turn_steps=4, tool_call_sanitize=False)
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("read")

    # The Read tool got an empty args dict; greetings is NOT in the
    # tool-result message (since no file_path was provided).
    tool_results = [m for m in agent.messages if m.get("role") == "tool"]
    combined = " ".join(str(m.get("content", "")) for m in tool_results)
    assert "greetings" not in combined
