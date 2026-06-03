"""Narrate-without-act recovery (runtime.py).

When a turn makes ZERO tool calls and the model ends on a future-tense
intent ("I'll run the tests") instead of doing it — a common small/local
model failure — athena nudges it (cfg.narrate_reprompt_attempts times) to
emit the actual tool call and re-streams, rather than silently wasting
the turn. These tests pin that recovery via a scripted stub provider.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk

_DONE = "All done: the tests pass and the change is in place."
_NARRATE = "I'll run the tests now."


class _ScriptedProvider:
    """Yields a scripted content string per model call (no tool calls).
    The last script repeats if the loop calls more times than scripted."""

    name = "scripted"
    requires_api_key = False

    def __init__(self, scripts: list[str]) -> None:
        self.scripts = scripts
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        idx = min(self.calls, len(self.scripts) - 1)
        self.calls += 1
        yield StreamChunk("content", self.scripts[idx])
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["scripted"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _nudges(agent: Agent) -> list[dict]:
    return [
        m
        for m in agent.messages
        if m.get("role") == "user" and "[athena]" in (m.get("content") or "")
    ]


def test_narrate_without_act_triggers_one_reprompt(isolated_home: Path, workspace: Path) -> None:
    """Narration on round 1 → a nudge is injected and the model is
    re-streamed; round 2 finishes cleanly. Two model calls, one nudge."""
    cfg = Config(model="scripted", narrate_reprompt_attempts=1)
    provider = _ScriptedProvider([_NARRATE, _DONE])
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("please run the tests")

    assert provider.calls == 2, "model should have been re-prompted once"
    nudges = _nudges(agent)
    assert len(nudges) == 1
    assert "did not call a tool" in nudges[0]["content"]


def test_reprompt_disabled_when_zero(isolated_home: Path, workspace: Path) -> None:
    """narrate_reprompt_attempts=0 keeps the old warn-only behaviour:
    the turn completes after one call, no nudge injected."""
    cfg = Config(model="scripted", narrate_reprompt_attempts=0)
    provider = _ScriptedProvider([_NARRATE, _DONE])
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("please run the tests")

    assert provider.calls == 1
    assert _nudges(agent) == []


def test_normal_completion_is_not_reprompted(isolated_home: Path, workspace: Path) -> None:
    """A turn that ends on a real conclusion (not a narrated intent) is
    NOT nudged — one call, no nudge."""
    cfg = Config(model="scripted", narrate_reprompt_attempts=1)
    provider = _ScriptedProvider([_DONE])
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("are we done?")

    assert provider.calls == 1
    assert _nudges(agent) == []


def test_reprompt_is_bounded(isolated_home: Path, workspace: Path) -> None:
    """If the model narrates on EVERY call, the nudge fires at most
    narrate_reprompt_attempts times and then the turn is accepted —
    no infinite loop."""
    cfg = Config(model="scripted", narrate_reprompt_attempts=1, max_turn_steps=25)
    provider = _ScriptedProvider([_NARRATE])  # always narrates
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("please run the tests")

    # call 1 narrates → nudge; call 2 narrates → out of nudges → accept.
    assert provider.calls == 2
    assert len(_nudges(agent)) == 1
