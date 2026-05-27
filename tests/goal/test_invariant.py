"""/goal invariant: persistence, system prompt injection, slash command."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.commands import get_command
from athena.goal.invariant import (
    GOAL_HEADER,
    clear_goal,
    format_for_system_prompt,
    get_goal,
    goal_path,
    set_goal,
)


def test_get_returns_none_when_no_file(tmp_path: Path):
    assert get_goal(tmp_path) is None


def test_set_writes_goal(tmp_path: Path):
    set_goal(tmp_path, "write idiomatic Rust")
    assert goal_path(tmp_path).read_text(encoding="utf-8").strip() == "write idiomatic Rust"


def test_set_strips_whitespace(tmp_path: Path):
    set_goal(tmp_path, "   write tests then commit   \n")
    assert get_goal(tmp_path) == "write tests then commit"


def test_set_rejects_empty(tmp_path: Path):
    with pytest.raises(ValueError, match="must not be empty"):
        set_goal(tmp_path, "   ")


def test_get_returns_none_for_blank_file(tmp_path: Path):
    goal_path(tmp_path).write_text("   \n", encoding="utf-8")
    assert get_goal(tmp_path) is None


def test_clear_removes_file(tmp_path: Path):
    set_goal(tmp_path, "x")
    assert clear_goal(tmp_path) is True
    assert get_goal(tmp_path) is None
    # Idempotent:
    assert clear_goal(tmp_path) is False


def test_format_includes_header():
    block = format_for_system_prompt("be concise")
    assert GOAL_HEADER in block
    assert "be concise" in block


def test_goal_persists_across_reload(tmp_path: Path):
    set_goal(tmp_path, "phase 1 goal")
    # Simulate a fresh process reading the file:
    assert get_goal(tmp_path) == "phase 1 goal"


def test_goal_appears_in_system_prompt(tmp_path: Path):
    """build_system_prompt appends the goal block when ``goal`` is passed."""
    from athena.prompts.system import build_system_prompt

    prompt = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5-coder:14b",
        goal="prefer composition over inheritance",
    )
    assert GOAL_HEADER in prompt
    assert "prefer composition over inheritance" in prompt
    # Goal is at the end (most authoritative position).
    assert prompt.rstrip().endswith("prefer composition over inheritance")


def test_no_goal_no_block_in_system_prompt(tmp_path: Path):
    from athena.prompts.system import build_system_prompt

    prompt = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5-coder:14b",
        goal=None,
    )
    assert GOAL_HEADER not in prompt


# ---- Slash command -----------------------------------------------------


class _FakeAgent:
    def __init__(self, profile_dir: Path):
        self._pd = profile_dir
        self.reloaded = 0
        self.goal: str | None = None

    def _profile_dir(self) -> Path:
        return self._pd

    def reload_goal(self) -> None:
        self.reloaded += 1
        self.goal = get_goal(self._pd)


def test_goal_command_sets(tmp_path: Path):
    cmd = get_command("goal")
    agent = _FakeAgent(tmp_path)
    cmd(agent, "write tests for the goal invariant module")
    assert get_goal(tmp_path) == "write tests for the goal invariant module"
    assert agent.goal == "write tests for the goal invariant module"
    assert agent.reloaded == 1


def test_goal_command_show_when_none(tmp_path: Path, capsys):
    cmd = get_command("goal")
    agent = _FakeAgent(tmp_path)
    cmd(agent, "show")
    assert agent.reloaded == 0


def test_goal_command_clear(tmp_path: Path):
    cmd = get_command("goal")
    agent = _FakeAgent(tmp_path)
    set_goal(tmp_path, "preexisting")
    cmd(agent, "clear")
    assert get_goal(tmp_path) is None
    assert agent.goal is None
    assert agent.reloaded == 1


def test_goal_command_empty_arg_shows():
    """Bare `/goal` is shorthand for `/goal show`."""
    cmd = get_command("goal")
    agent = _FakeAgent(Path("/tmp/nonexistent_for_test"))
    # Doesn't raise; just shows (or info-no-goal).
    cmd(agent, "")
