"""T7-01.1 — run_headless core tests.

Inject a stub Agent so the tests don't need a real model / a
real session store / a real Ollama. The shape the runner reads
off the agent (model, session_id, stats, _last_assistant_text)
is what matters; the agent loop's internals stay untouched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.headless.runner import run_headless


# ---------------------------------------------------------------
# Stub agent — minimal surface for run_headless to read.
# ---------------------------------------------------------------


class _Stats:
    def __init__(self, *, prompt=0, eval_=0, cache_read=0, cache_creation=0,
                 tool_call_counts=None):
        self.prompt_tokens = prompt
        self.eval_tokens = eval_
        self.cache_read_tokens = cache_read
        self.cache_creation_tokens = cache_creation
        self.tool_call_counts = dict(tool_call_counts or {})


class _StubAgent:
    """Records the run_turn arg + lets the test trigger raises
    (KeyboardInterrupt for interrupt/timeout; other exceptions
    for the error path)."""

    def __init__(
        self,
        *,
        cfg: Any,
        workspace: Path,
        model: str | None = None,
        assistant_text: str = "synthetic answer",
        raise_on_run_turn: Exception | None = None,
        stats: _Stats | None = None,
    ):
        self.cfg = cfg
        self.workspace = workspace
        self.model = model or getattr(cfg, "model", "stub-model")
        self.session_id = "s-stub-1"
        self._last_assistant_text = assistant_text
        self.stats = stats or _Stats(
            prompt=42, eval_=21,
            tool_call_counts={"Bash": 2, "Read": 5},
        )
        self._raise = raise_on_run_turn
        self.run_turn_calls: list[str] = []
        self.closed = False

    def run_turn(self, task: str) -> None:
        self.run_turn_calls.append(task)
        if self._raise is not None:
            raise self._raise

    def close(self) -> None:
        self.closed = True


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(
        model="stub-model",
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------


def test_success_returns_ok(tmp_path: Path):
    factory_calls: list[dict] = []
    agent_holder: list[_StubAgent] = []

    def _factory(**kw):
        factory_calls.append(kw)
        a = _StubAgent(**kw)
        agent_holder.append(a)
        return a

    result = run_headless(
        "summarise the codebase",
        cfg=_cfg(),
        workspace=tmp_path,
        _agent_factory=_factory,
    )
    assert result.status == "ok"
    assert result.exit_code() == 0
    assert result.run_id.startswith("r-")
    assert result.task == "summarise the codebase"
    assert result.workspace == str(tmp_path)
    assert result.model == "stub-model"
    assert result.session_id == "s-stub-1"
    assert result.assistant_text == "synthetic answer"
    assert result.tokens == {
        "prompt": 42, "completion": 21,
        "cache_read": 0, "cache_creation": 0,
    }
    # Tool calls listed in desc-count order.
    assert result.tool_calls == [
        {"name": "Read", "count": 5},
        {"name": "Bash", "count": 2},
    ]
    # The stub agent saw the task + got closed at teardown.
    assert agent_holder[0].run_turn_calls == ["summarise the codebase"]
    assert agent_holder[0].closed is True


def test_run_id_minted_when_absent(tmp_path: Path):
    result = run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert result.run_id.startswith("r-")
    assert len(result.run_id) == 2 + 12


def test_run_id_passed_through(tmp_path: Path):
    result = run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        run_id="r-batch-001",
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert result.run_id == "r-batch-001"


def test_timestamps_and_duration_present(tmp_path: Path):
    result = run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert result.started_at.endswith("Z")
    assert result.finished_at.endswith("Z")
    assert result.duration_s >= 0


# ---------------------------------------------------------------
# invalid input → status="invalid", exit code 2
# ---------------------------------------------------------------


def test_empty_task_invalid(tmp_path: Path):
    result = run_headless(
        "", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert result.status == "invalid"
    assert result.exit_code() == 2
    assert "empty" in result.error


def test_whitespace_only_task_invalid(tmp_path: Path):
    result = run_headless(
        "   \n  ", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert result.status == "invalid"
    assert result.exit_code() == 2


def test_nonexistent_workspace_invalid(tmp_path: Path):
    result = run_headless(
        "x", cfg=_cfg(), workspace=tmp_path / "nope",
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert result.status == "invalid"
    assert "does not exist" in result.error


def test_non_directory_workspace_invalid(tmp_path: Path):
    bogus = tmp_path / "a.txt"
    bogus.write_text("file, not a directory", encoding="utf-8")
    result = run_headless(
        "x", cfg=_cfg(), workspace=bogus,
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert result.status == "invalid"
    assert "not a directory" in result.error


# ---------------------------------------------------------------
# error path → status="error", exit code 1
# ---------------------------------------------------------------


def test_agent_exception_returns_error(tmp_path: Path):
    result = run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=lambda **kw: _StubAgent(
            raise_on_run_turn=RuntimeError("model unreachable"), **kw,
        ),
    )
    assert result.status == "error"
    assert result.exit_code() == 1
    assert "model unreachable" in result.error
    assert "RuntimeError" in result.error


# ---------------------------------------------------------------
# interrupt → status="interrupted", exit code 130
# ---------------------------------------------------------------


def test_keyboard_interrupt_returns_interrupted(tmp_path: Path):
    result = run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=lambda **kw: _StubAgent(
            raise_on_run_turn=KeyboardInterrupt(), **kw,
        ),
    )
    assert result.status == "interrupted"
    assert result.exit_code() == 130
    assert "interrupted by user" in result.error


# ---------------------------------------------------------------
# UI callback fires
# ---------------------------------------------------------------


def test_on_info_callback_fires(tmp_path: Path):
    msgs: list[str] = []
    run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        on_info=msgs.append,
        _agent_factory=lambda **kw: _StubAgent(**kw),
    )
    assert any("starting headless run" in m for m in msgs)
    # The run_id is included in the chatter so an operator
    # tailing stderr can correlate.
    assert any("run_id=" in m for m in msgs)


# ---------------------------------------------------------------
# agent.close() is always called (even on error)
# ---------------------------------------------------------------


def test_agent_close_always_called_on_success(tmp_path: Path):
    holder: list[_StubAgent] = []

    def _factory(**kw):
        a = _StubAgent(**kw)
        holder.append(a)
        return a

    run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=_factory,
    )
    assert holder[0].closed is True


def test_agent_close_called_on_error(tmp_path: Path):
    holder: list[_StubAgent] = []

    def _factory(**kw):
        a = _StubAgent(raise_on_run_turn=RuntimeError("boom"), **kw)
        holder.append(a)
        return a

    run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=_factory,
    )
    assert holder[0].closed is True


# ---------------------------------------------------------------
# tokens/tool_calls populated from stats
# ---------------------------------------------------------------


def test_empty_stats_produces_zero_tokens(tmp_path: Path):
    """Agent with empty Stats → tokens dict has zeros, not
    missing keys (the envelope shape is stable)."""
    factory = lambda **kw: _StubAgent(
        stats=_Stats(), **kw,
    )
    result = run_headless(
        "x", cfg=_cfg(), workspace=tmp_path,
        _agent_factory=factory,
    )
    assert result.tokens == {
        "prompt": 0, "completion": 0,
        "cache_read": 0, "cache_creation": 0,
    }
    assert result.tool_calls == []
