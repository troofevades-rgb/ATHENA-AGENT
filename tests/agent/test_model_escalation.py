"""Struggle-based model escalation (runtime.py:_maybe_escalate_model).

When the local model gets stuck (the identical-tool-call circuit breaker
would trip) and cfg.routing_enabled is set, athena escalates the rest of
the turn to cfg.routing_escalation_model instead of halting, then reverts
to the base model on the next turn (local-first). OFF by default.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk


class _Base:
    """Local model that loops the SAME tool call (tripping the breaker)
    for its first ``stuck_calls`` invocations, then returns a final
    answer — lets a later turn complete on the base model."""

    name = "base-local"
    requires_api_key = False

    def __init__(self, stuck_calls: int = 999) -> None:
        self.calls = 0
        self.stuck_calls = stuck_calls

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        if self.calls <= self.stuck_calls:
            yield StreamChunk(
                "tool_call",
                {"id": f"c{self.calls}", "name": "Read", "arguments": {"file_path": "/nope"}},
            )
            yield StreamChunk("end", None)
        else:
            yield StreamChunk("content", "Done on the base model.")
            yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["base-local"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


class _Rescue:
    """Strong model: completes immediately (no tool calls)."""

    name = "strong"
    requires_api_key = False

    def __init__(self) -> None:
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        yield StreamChunk("content", "Recovered by the strong model.")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["strong"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


@pytest.fixture
def rescue(monkeypatch: pytest.MonkeyPatch) -> _Rescue:
    """Patch the resolver so escalation resolves to the fake strong model."""
    r = _Rescue()
    monkeypatch.setattr(
        "athena.providers.credential_pool.profile_pool",
        lambda profile=None: object(),
    )
    monkeypatch.setattr(
        "athena.providers.runtime_resolver.resolve_provider",
        lambda model, cfg, pool: (r, "strong-bare"),
    )
    return r


def test_escalates_on_stuck_loop_and_recovers(
    isolated_home: Path, workspace: Path, rescue: _Rescue
) -> None:
    cfg = Config(
        model="base-local",
        routing_enabled=True,
        routing_escalation_model="strong",
        max_identical_tool_calls=2,
        max_turn_steps=25,
    )
    base = _Base()
    agent = Agent(cfg, workspace, provider=base)

    agent.run_turn("do the thing")

    assert base.calls == 2  # looped until the breaker would have tripped
    assert rescue.calls >= 1  # the strong model took over and finished
    assert agent._last_stop_reason == "completed"
    assert agent.model == "strong-bare"  # escalated (reverts next turn)


def test_no_escalation_when_disabled(isolated_home: Path, workspace: Path, rescue: _Rescue) -> None:
    cfg = Config(
        model="base-local",
        routing_enabled=False,  # off → breaker halts as before
        routing_escalation_model="strong",
        max_identical_tool_calls=2,
    )
    base = _Base()
    agent = Agent(cfg, workspace, provider=base)

    agent.run_turn("x")

    assert base.calls == 2
    assert rescue.calls == 0
    assert agent._last_stop_reason == "circuit_breaker:identical_tool_calls"


def test_no_escalation_without_target_model(
    isolated_home: Path, workspace: Path, rescue: _Rescue
) -> None:
    cfg = Config(
        model="base-local",
        routing_enabled=True,
        routing_escalation_model="",  # enabled but no target → no-op
        max_identical_tool_calls=2,
    )
    base = _Base()
    agent = Agent(cfg, workspace, provider=base)

    agent.run_turn("x")

    assert rescue.calls == 0
    assert agent._last_stop_reason == "circuit_breaker:identical_tool_calls"


def test_reverts_to_base_on_next_turn(
    isolated_home: Path, workspace: Path, rescue: _Rescue
) -> None:
    cfg = Config(
        model="base-local",
        routing_enabled=True,
        routing_escalation_model="strong",
        max_identical_tool_calls=2,
        max_turn_steps=25,
    )
    base = _Base(stuck_calls=2)  # stuck on turn 1; final answer on call 3
    agent = Agent(cfg, workspace, provider=base)

    agent.run_turn("turn one")  # stuck → escalate → strong finishes
    assert agent.model == "strong-bare"
    assert agent._escalated is True

    agent.run_turn("turn two")  # reverts to base; base returns final
    assert agent._escalated is False
    assert agent.model == "base-local"  # reverted local-first
    assert base.calls == 3  # base ran again on turn 2
    assert rescue.calls == 1  # strong used only on turn 1
