"""Tests for ``/clear`` — reset conversation, keep the system prompt."""

from __future__ import annotations

from types import SimpleNamespace

from athena.commands.clear_cmd import cmd_clear


def test_clear_calls_agent_reset() -> None:
    """``/clear`` is a thin wrapper over agent.reset(). The contract
    is "call reset, return empty string"; anything else is a regression."""
    calls: list[str] = []

    def _reset() -> None:
        calls.append("reset")

    agent = SimpleNamespace(reset=_reset)
    result = cmd_clear(agent, "")
    assert calls == ["reset"]
    assert result == ""


def test_clear_ignores_args() -> None:
    """Slash args are passed through but ``/clear`` doesn't use them.
    Extra args should not raise or change behavior."""
    calls: list[str] = []
    agent = SimpleNamespace(reset=lambda: calls.append("reset"))
    cmd_clear(agent, "")
    cmd_clear(agent, "ignored")
    cmd_clear(agent, "ignored garbage here")
    assert calls == ["reset", "reset", "reset"]


def test_clear_returns_empty_string() -> None:
    """The slash dispatcher uses the return value for echo text;
    empty string means "no echo, just do the side effect"."""
    agent = SimpleNamespace(reset=lambda: None)
    assert cmd_clear(agent, "") == ""
