"""Cache markers are stripped before session-store persistence (T2-01.6)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk


class _BareProvider:
    name = "anthropic"
    requires_api_key = False

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        yield StreamChunk("content", "ok")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["fake"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _has_cache_control(msg: dict[str, Any]) -> bool:
    if "cache_control" in msg:
        return True
    content = msg.get("content")
    if isinstance(content, list):
        return any(isinstance(block, dict) and "cache_control" in block for block in content)
    return False


def test_persist_strips_marker_planted_on_message_dict(
    isolated_home: Path, workspace: Path
) -> None:
    """A message with a cache_control field at the top level is
    written WITHOUT that field."""
    cfg = Config(model="fake-claude", cache_strategy="system_and_3")
    agent = Agent(cfg, workspace, provider=_BareProvider())

    poisoned = {
        "role": "user",
        "content": "hello",
        "cache_control": {"type": "ephemeral"},
    }
    agent._persist_message(poisoned)

    # The original dict is unchanged (we stripped a deepcopy).
    assert poisoned.get("cache_control") == {"type": "ephemeral"}

    # The persisted version has no marker.
    persisted = list(agent.session_store.load(agent.session_id))
    matching = [m for m in persisted if m.get("content") == "hello"]
    assert matching, f"persisted message not found; got {persisted}"
    assert not _has_cache_control(matching[0])


def test_persist_strips_marker_on_content_block(isolated_home: Path, workspace: Path) -> None:
    cfg = Config(model="fake-claude", cache_strategy="system_and_3")
    agent = Agent(cfg, workspace, provider=_BareProvider())

    poisoned = {
        "role": "user",
        "content": [
            {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}},
        ],
    }
    agent._persist_message(poisoned)

    persisted = list(agent.session_store.load(agent.session_id))
    matching = [
        m
        for m in persisted
        if isinstance(m.get("content"), list)
        and m["content"]
        and m["content"][0].get("text") == "hi"
    ]
    assert matching, f"persisted message not found; got {persisted}"
    assert not _has_cache_control(matching[0])


def test_run_turn_does_not_persist_markers(isolated_home: Path, workspace: Path) -> None:
    """End-to-end: even with cache_strategy=system_and_3 on an Anthropic
    provider, the session JSONL never carries cache_control markers."""
    cfg = Config(model="fake-claude", cache_strategy="system_and_3")
    agent = Agent(cfg, workspace, provider=_BareProvider())
    agent.run_turn("hello")

    persisted = list(agent.session_store.load(agent.session_id))
    for m in persisted:
        assert not _has_cache_control(m), f"persisted message carries cache_control: {m}"
