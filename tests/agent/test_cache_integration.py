"""Cache-marker integration: the Agent attaches cache_control markers
to messages sent to Anthropic-flavoured providers (T2-01.4 + T2-01.5).

Asserts at the Agent layer rather than the provider layer because
the cache-marker dispatch lives in ``Agent._messages_with_cache_markers``;
the provider receives already-marked messages. This places the
contract at the seam the Agent owns.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import Capabilities, StreamChunk


class _RecordingProvider:
    """Captures every (messages, tools) tuple sent to stream_chat."""

    def __init__(self, *, name: str = "anthropic") -> None:
        self.name = name
        self.requires_api_key = False
        self.calls: list[list[dict[str, Any]]] = []
        # Cache-marker dispatch reads anthropic_cache_markers off the
        # provider's Capabilities. Default to "Anthropic-flavoured"
        # because most tests in this file want markers applied; the
        # negative-path tests override ``name`` AND set this False.
        self._caps = Capabilities(
            prompt_caching=True,
            anthropic_cache_markers=(name in {"anthropic", "openrouter", "nous"}),
        )

    def capabilities(self, model: str | None = None) -> Capabilities:
        return self._caps

    def stream_chat(
        self, *, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> Iterator[StreamChunk]:
        # Snapshot the messages the Agent actually sent.
        import copy as _copy

        self.calls.append(_copy.deepcopy(messages))
        yield StreamChunk("content", "ok")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["fake-claude"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _make_agent(provider: Any, workspace: Path, **cfg_overrides: Any) -> Agent:
    cfg = Config(model="fake-claude")
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    return Agent(cfg, workspace, provider=provider)


def _find_cache_marker(msgs: list[dict[str, Any]]) -> bool:
    """True iff any message or any text block has a cache_control field."""
    for m in msgs:
        if "cache_control" in m:
            return True
        c = m.get("content")
        if isinstance(c, list):
            for block in c:
                if isinstance(block, dict) and "cache_control" in block:
                    return True
    return False


# ---------------------------------------------------------------------------
# Anthropic provider -> markers applied
# ---------------------------------------------------------------------------


def test_anthropic_provider_gets_cache_markers(isolated_home: Path, workspace: Path) -> None:
    provider = _RecordingProvider(name="anthropic")
    agent = _make_agent(provider, workspace, cache_strategy="system_and_3")
    agent.run_turn("hello")

    assert provider.calls, "provider was not called"
    assert _find_cache_marker(provider.calls[-1]), (
        "Anthropic provider received messages with NO cache_control field"
    )


def test_anthropic_provider_5m_default_ttl(isolated_home: Path, workspace: Path) -> None:
    """5m TTL omits the ttl key from the marker dict."""
    provider = _RecordingProvider(name="anthropic")
    agent = _make_agent(provider, workspace, cache_strategy="system_and_3")
    agent.run_turn("hi")

    markers = []
    for m in provider.calls[-1]:
        if "cache_control" in m:
            markers.append(m["cache_control"])
        c = m.get("content")
        if isinstance(c, list):
            for block in c:
                if isinstance(block, dict) and "cache_control" in block:
                    markers.append(block["cache_control"])
    assert markers, "no cache markers found at all"
    # Every marker is the 5m shape: {"type": "ephemeral"} with no ttl key.
    for marker in markers:
        assert marker == {"type": "ephemeral"}, marker


def test_anthropic_provider_1h_ttl(isolated_home: Path, workspace: Path) -> None:
    provider = _RecordingProvider(name="anthropic")
    agent = _make_agent(
        provider,
        workspace,
        cache_strategy="system_and_3",
        prompt_cache_ttl="1h",
    )
    agent.run_turn("hi")

    found_1h = False
    for m in provider.calls[-1]:
        marker = m.get("cache_control")
        if isinstance(marker, dict) and marker.get("ttl") == "1h":
            found_1h = True
            break
        c = m.get("content")
        if isinstance(c, list):
            for block in c:
                if isinstance(block, dict):
                    bm = block.get("cache_control")
                    if isinstance(bm, dict) and bm.get("ttl") == "1h":
                        found_1h = True
                        break
    assert found_1h, "1h TTL marker not surfaced anywhere in the sent messages"


# ---------------------------------------------------------------------------
# strategy="none" -> markers skipped
# ---------------------------------------------------------------------------


def test_cache_strategy_none_skips_markers(isolated_home: Path, workspace: Path) -> None:
    provider = _RecordingProvider(name="anthropic")
    agent = _make_agent(provider, workspace, cache_strategy="none")
    agent.run_turn("hi")

    assert not _find_cache_marker(provider.calls[-1]), (
        "cache markers were applied even though cache_strategy=none"
    )


# ---------------------------------------------------------------------------
# OpenRouter / Nous -> markers applied as native_anthropic=False
# ---------------------------------------------------------------------------


def test_openrouter_provider_gets_markers_openai_shape(
    isolated_home: Path, workspace: Path
) -> None:
    """OpenRouter routes the marker as an OpenAI-compat field. The
    Agent passes native_anthropic=False; the resulting message shape
    still carries cache_control somewhere on each marked message."""
    provider = _RecordingProvider(name="openrouter")
    agent = _make_agent(provider, workspace, cache_strategy="system_and_3")
    agent.run_turn("hi")

    assert _find_cache_marker(provider.calls[-1]), (
        "OpenRouter provider received messages with NO cache_control field"
    )


def test_nous_provider_gets_markers(isolated_home: Path, workspace: Path) -> None:
    provider = _RecordingProvider(name="nous")
    agent = _make_agent(provider, workspace, cache_strategy="system_and_3")
    agent.run_turn("hi")

    assert _find_cache_marker(provider.calls[-1])


# ---------------------------------------------------------------------------
# Non-cache-aware providers -> markers NOT applied
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["ollama", "openai", "openai_compat", "google", "fake"])
def test_non_anthropic_providers_skip_markers(
    isolated_home: Path, workspace: Path, name: str
) -> None:
    provider = _RecordingProvider(name=name)
    agent = _make_agent(provider, workspace, cache_strategy="system_and_3")
    agent.run_turn("hi")

    assert not _find_cache_marker(provider.calls[-1]), (
        f"provider {name!r} should NOT receive cache markers but did"
    )
