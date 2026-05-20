"""``/model`` re-resolves the provider when the new model routes
to a different one (T2-07 hotfix).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.commands.model_cmd import cmd_model as _slash_model
from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk


class _MinimalProvider:
    name = "ollama"
    requires_api_key = False

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["qwen2.5-coder:14b"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def test_slash_model_keeps_provider_when_routing_unchanged(
    isolated_home: Path, workspace: Path
) -> None:
    """Switching from one Ollama model to another Ollama model doesn't
    rebuild the provider — same instance stays in place."""
    cfg = Config(model="qwen2.5-coder:14b")
    agent = Agent(cfg, workspace, provider=_MinimalProvider())
    original_provider = agent.provider

    _slash_model(agent, "qwen2.5-coder:7b")
    assert agent.provider is original_provider
    assert agent.model == "qwen2.5-coder:7b"


def test_slash_model_swaps_provider_when_routing_changes(
    isolated_home: Path, workspace: Path, monkeypatch
) -> None:
    """``/model anthropic/...`` routes to a different provider —
    /model must re-resolve and swap so the next chat doesn't 404
    against the previous (e.g. Ollama) provider."""
    cfg = Config(model="qwen2.5-coder:14b")
    agent = Agent(cfg, workspace, provider=_MinimalProvider())
    original_provider = agent.provider

    # Stub resolve_provider so the test doesn't need real credentials.
    class _FakeAnthropic:
        name = "anthropic"
        requires_api_key = True

        def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
            yield StreamChunk("end", None)

        def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
            return content, []

        def list_models(self) -> list[str]:
            return []

        def show_model(self, model: str) -> dict[str, Any]:
            return {}

        def close(self) -> None:
            return None

    def fake_resolve(model, cfg, pool):
        # Strip the anthropic/ prefix and return a new provider.
        bare = model.split("/", 1)[1] if "/" in model else model
        return _FakeAnthropic(), bare

    monkeypatch.setattr(
        "athena.providers.runtime_resolver.resolve_provider",
        fake_resolve,
    )

    _slash_model(agent, "anthropic/claude-sonnet-latest")

    assert agent.provider is not original_provider
    assert agent.provider.name == "anthropic"
    # Bare model name (sans the provider prefix) is what lands.
    assert agent.model == "claude-sonnet-latest"
