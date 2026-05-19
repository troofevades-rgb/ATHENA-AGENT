"""Single-turn ``Agent.run_turn`` behaviour (T1-04.4).

``run_turn`` is sync and returns ``None``; the per-turn results live in
``agent.messages``, ``agent.tool_call_trace()``, and ``agent.stats``.
The spec skeleton's ``async`` / tuple-return assumptions do not match
athena's actual surface — see ``_PLAN.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from athena.agent.core import Agent
from athena.config import Config
from athena.provenance import FOREGROUND, get_current_write_origin
from athena.providers.base import StreamChunk

if TYPE_CHECKING:
    from .conftest import FakeProvider


def _make_agent(provider: Any, workspace: Path, **cfg_overrides: Any) -> Agent:
    cfg = Config(model="fake-model")
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    return Agent(cfg, workspace, provider=provider)


def test_run_turn_streams_plain_text(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """A scenario containing only ``content`` + ``end`` chunks lands in
    history as one assistant message; no tool calls."""
    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "Hello, "},
            {"kind": "content", "payload": "world."},
            {
                "kind": "usage",
                "payload": {"prompt_tokens": 10, "completion_tokens": 3},
            },
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace)
    agent.run_turn("hi")

    assistant_msgs = [m for m in agent.messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "Hello, world."
    assert "tool_calls" not in assistant_msgs[0]
    assert agent.tool_call_trace() == []
    assert agent.stats.prompt_tokens == 10
    assert agent.stats.eval_tokens == 3


def test_run_turn_persists_user_message_to_history(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """The user input lands in ``agent.messages`` as a ``user`` role
    message before the model is invoked."""
    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "ok"},
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace)
    agent.run_turn("please do the thing")

    user_msgs = [m for m in agent.messages if m.get("role") == "user"]
    assert any(m.get("content") == "please do the thing" for m in user_msgs)


def test_run_turn_records_provenance_foreground(
    isolated_home: Path,
    workspace: Path,
) -> None:
    """While ``run_turn`` is on the stack the ``write_origin``
    ContextVar reads as ``FOREGROUND``. Captured via a provider that
    snapshots the var at stream_chat time."""
    captured: list[str] = []

    class CapturingProvider:
        name = "fake-capture"
        requires_api_key = False

        def __init__(self) -> None:
            self.call_history: list[tuple] = []

        def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
            captured.append(get_current_write_origin())
            yield StreamChunk("content", "done")
            yield StreamChunk("end", None)

        def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
            return content, []

        def list_models(self) -> list[str]:
            return ["fake-model"]

        def show_model(self, model: str) -> dict[str, Any]:
            return {}

        def close(self) -> None:
            return None

    agent = _make_agent(CapturingProvider(), workspace)
    agent.run_turn("hi")

    assert captured == [FOREGROUND]


def test_run_turn_honors_keyboard_interrupt(
    isolated_home: Path,
    workspace: Path,
) -> None:
    """A ``KeyboardInterrupt`` raised mid-stream is caught; the turn
    records an interrupt marker in history and returns normally
    (does not re-raise)."""

    class InterruptingProvider:
        name = "fake-interrupt"
        requires_api_key = False

        def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
            yield StreamChunk("content", "partial")
            raise KeyboardInterrupt()

        def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
            return content, []

        def list_models(self) -> list[str]:
            return ["fake-model"]

        def show_model(self, model: str) -> dict[str, Any]:
            return {}

        def close(self) -> None:
            return None

    agent = _make_agent(InterruptingProvider(), workspace)
    # Must NOT raise.
    agent.run_turn("go")

    # Either a partial assistant message landed plus the interrupt
    # marker, or the assistant message is empty — both shapes are
    # acceptable. The invariant we assert is that the loop didn't
    # leak the exception.
    interrupt_marker = "[previous response was interrupted by the user]"
    user_msgs = [m for m in agent.messages if m.get("role") == "user"]
    assert any(m.get("content") == interrupt_marker for m in user_msgs), (
        f"interrupt marker not in user messages: {[m.get('content') for m in user_msgs]}"
    )


def test_run_turn_records_token_usage(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """Both OpenAI-style and Ollama-style usage field names land in
    ``agent.stats``. The agent normalises both into the same counters."""
    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "a"},
            {
                "kind": "usage",
                "payload": {"prompt_eval_count": 7, "eval_count": 2},
            },
            {"kind": "end", "payload": None},
        ]
    )
    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "b"},
            {
                "kind": "usage",
                "payload": {"prompt_tokens": 5, "completion_tokens": 1},
            },
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace)
    agent.run_turn("first")
    agent.run_turn("second")

    # Across two turns the prompt + eval token counters accumulate from
    # both naming conventions.
    assert agent.stats.prompt_tokens == 12
    assert agent.stats.eval_tokens == 3
