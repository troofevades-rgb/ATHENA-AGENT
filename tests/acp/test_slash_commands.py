"""ACP slash command handler."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from athena.acp.slash_commands import handle_slash
from athena.steer.queue import GLOBAL_STEER_QUEUE


@pytest.fixture(autouse=True)
def reset_queue() -> None:
    """The steer queue is process-global; reset between tests."""
    GLOBAL_STEER_QUEUE._q.clear()  # type: ignore[attr-defined]


def _stub_agent(profile_dir: Path | None = None):
    agent = MagicMock()
    agent.goal = None
    agent.reload_goal = MagicMock()
    if profile_dir is not None:
        agent._profile_dir = MagicMock(return_value=profile_dir)
    else:
        agent._profile_dir = MagicMock(side_effect=Exception("no profile"))
    return agent


# ---- steer ----------------------------------------------------------


async def test_steer_pushes_to_queue() -> None:
    result = await handle_slash({
        "session_id": "s1", "command": "steer", "argument": "focus on tests",
    }, sessions={})
    assert "steer queued" in result["result"]
    assert GLOBAL_STEER_QUEUE.list("s1") == ["focus on tests"]


async def test_steer_strips_leading_slash() -> None:
    result = await handle_slash({
        "session_id": "s1", "command": "/steer", "argument": "x",
    }, sessions={})
    assert "steer queued" in result["result"]


async def test_steer_without_argument_shows_usage() -> None:
    result = await handle_slash({
        "session_id": "s1", "command": "steer",
    }, sessions={})
    assert "usage" in result["result"]
    assert GLOBAL_STEER_QUEUE.list("s1") == []


# ---- queue ----------------------------------------------------------


async def test_queue_lists_pending() -> None:
    GLOBAL_STEER_QUEUE.push("s1", "first thing")
    GLOBAL_STEER_QUEUE.push("s1", "second thing")
    result = await handle_slash({
        "session_id": "s1", "command": "queue",
    }, sessions={})
    assert "first thing" in result["result"]
    assert "second thing" in result["result"]


async def test_queue_empty_shows_message() -> None:
    result = await handle_slash({
        "session_id": "s1", "command": "queue",
    }, sessions={})
    assert "(no pending" in result["result"]


async def test_queue_clear_drops_all() -> None:
    GLOBAL_STEER_QUEUE.push("s1", "one")
    GLOBAL_STEER_QUEUE.push("s1", "two")
    result = await handle_slash({
        "session_id": "s1", "command": "queue", "argument": "clear",
    }, sessions={})
    assert "2 pending" in result["result"]
    assert GLOBAL_STEER_QUEUE.list("s1") == []


# ---- goal ----------------------------------------------------------


async def test_goal_with_no_session_in_dict_returns_no_goal_set() -> None:
    """When the session isn't in the sessions dict, /goal can't reach
    the agent's profile_dir, so it surfaces a clean message."""
    result = await handle_slash({
        "session_id": "s1", "command": "goal",
    }, sessions={})
    assert "no goal set" in result["result"]


async def test_goal_set_writes_via_agent(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    agent = _stub_agent(profile_dir)
    result = await handle_slash({
        "session_id": "s1", "command": "goal",
        "argument": "write idiomatic Rust",
    }, sessions={"s1": agent})
    assert "goal set" in result["result"]
    # Goal file written.
    assert (profile_dir / "goal.txt").read_text(
        encoding="utf-8",
    ).strip() == "write idiomatic Rust"
    # Agent's goal field updated AND system prompt rebuilt.
    assert agent.goal == "write idiomatic Rust"
    agent.reload_goal.assert_called_once()


async def test_goal_show_after_set(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "goal.txt").write_text("be terse", encoding="utf-8")
    agent = _stub_agent(profile_dir)
    result = await handle_slash({
        "session_id": "s1", "command": "goal",
    }, sessions={"s1": agent})
    assert "be terse" in result["result"]


async def test_goal_clear_removes_goal(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "goal.txt").write_text("focus on perf", encoding="utf-8")
    agent = _stub_agent(profile_dir)
    agent.goal = "focus on perf"
    result = await handle_slash({
        "session_id": "s1", "command": "goal", "argument": "clear",
    }, sessions={"s1": agent})
    assert "goal cleared" in result["result"]
    assert not (profile_dir / "goal.txt").exists()
    assert agent.goal is None


# ---- unknown / malformed -----------------------------------------


async def test_unknown_command_returns_message() -> None:
    result = await handle_slash({
        "session_id": "s1", "command": "burn",
    }, sessions={})
    assert "unknown" in result["result"]


async def test_missing_session_id_returns_error() -> None:
    result = await handle_slash({
        "command": "steer", "argument": "x",
    }, sessions={})
    assert "session_id" in result["result"]


async def test_command_with_leading_slash_normalized() -> None:
    result = await handle_slash({
        "session_id": "s1", "command": "/queue",
    }, sessions={})
    # Returns the queue listing, not an unknown-command error.
    assert "unknown" not in result["result"]
