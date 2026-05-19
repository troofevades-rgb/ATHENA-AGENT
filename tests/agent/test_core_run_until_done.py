"""Multi-turn ``Agent.run_until_done`` behaviour (T1-04.5).

``run_until_done`` is a thin wrapper around ``run_turn`` that optionally
overrides ``cfg.max_turn_steps`` for the call. The "loop until no more
tool calls" semantics actually live inside ``run_turn``'s ``for step in
range(max_steps)`` loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from athena.agent.core import Agent
from athena.config import Config

if TYPE_CHECKING:
    from .conftest import FakeProvider


def _make_agent(provider: Any, workspace: Path, **cfg_overrides: Any) -> Agent:
    cfg = Config(model="fake-model")
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    return Agent(cfg, workspace, provider=provider)


def test_run_until_done_stops_on_no_more_tool_calls(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """One streaming scenario with no tool calls completes in one round."""
    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "all done"},
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace)
    agent.run_until_done("hi")

    assistant_msgs = [m for m in agent.messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert agent.last_assistant_message() == "all done"


def test_run_until_done_respects_max_iterations_override(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """``max_iterations`` temporarily overrides ``cfg.max_turn_steps``
    for the duration of the call and restores it afterward."""
    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "ok"},
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace, max_turn_steps=20)
    assert agent.cfg.max_turn_steps == 20

    # Patch run_turn to capture the value of cfg.max_turn_steps that's
    # active when the override is supposed to be in effect.
    seen: list[int] = []
    original_run_turn = agent.run_turn

    def spy(user_input: str) -> None:
        seen.append(agent.cfg.max_turn_steps)
        original_run_turn(user_input)

    agent.run_turn = spy  # type: ignore[method-assign]
    agent.run_until_done("hi", max_iterations=3)

    assert seen == [3], f"override not visible inside run_turn: {seen}"
    # Restored after the call returns.
    assert agent.cfg.max_turn_steps == 20


def test_run_until_done_drains_pending_steers(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """A ``/steer`` queued before the next prompt is injected as a
    synthetic user message ahead of the actual user prompt."""
    from athena.steer.queue import GLOBAL_STEER_QUEUE

    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "ack"},
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace)
    try:
        GLOBAL_STEER_QUEUE.push(agent.session_id, "remember: keep it short")
        agent.run_until_done("do the thing")

        user_msgs = [m for m in agent.messages if m.get("role") == "user"]
        contents = [m.get("content") for m in user_msgs]
        # The steer is injected as "[/steer] <msg>" before the user prompt.
        assert "[/steer] remember: keep it short" in contents, (
            f"steer not injected; user messages: {contents}"
        )
        # And the original user prompt still lands.
        assert "do the thing" in contents
    finally:
        # Defensive cleanup so the global queue doesn't leak into other tests.
        GLOBAL_STEER_QUEUE.clear(agent.session_id)


def test_run_until_done_persists_messages_via_session_store(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """User and assistant messages are appended through the agent's
    SessionStore. We assert against ``agent.session_store`` directly
    rather than searching the filesystem because ``config.CONFIG_DIR``
    is frozen at module-load time and is not affected by the
    ``isolated_home`` fixture (a known wart).
    """
    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "persistence check"},
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace)
    assert agent.session_store is not None, "Agent.__init__ did not construct a SessionStore"

    agent.run_until_done("write me down")

    turns = list(agent.session_store.load(agent.session_id))
    contents = [t.get("content", "") for t in turns if isinstance(t, dict)]
    assert any("write me down" in (c or "") for c in contents), (
        f"user message not persisted; turns: {turns}"
    )
    assert any("persistence check" in (c or "") for c in contents), (
        f"assistant message not persisted; turns: {turns}"
    )


def test_run_until_done_injects_goal_into_system_prompt(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch,
) -> None:
    """A goal set via ``athena.goal.invariant.set_goal`` surfaces in the
    agent's system prompt and on the ``agent.goal`` attribute."""
    from athena import config as config_mod
    from athena.goal.invariant import set_goal

    # CONFIG_DIR is frozen at module-load time before the
    # isolated_home monkeypatch takes effect. Redirect the lazy
    # profile_dir() call to the isolated tree for the duration of
    # this test.
    isolated_athena = isolated_home / ".athena"
    isolated_athena.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", isolated_athena)

    profile_root = isolated_athena / "profiles" / "default"
    profile_root.mkdir(parents=True, exist_ok=True)
    set_goal(profile_root, "ship the v0.2 release before EOD")

    fake_provider.add_scenario(
        [
            {"kind": "content", "payload": "ok"},
            {"kind": "end", "payload": None},
        ]
    )
    agent = _make_agent(fake_provider, workspace)
    assert agent.goal == "ship the v0.2 release before EOD"
    system_text = agent.messages[0].get("content") or ""
    assert "ship the v0.2 release" in system_text, (
        f"goal not in system prompt; first 300 chars: {system_text[:300]!r}"
    )
