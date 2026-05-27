"""Runner contract — verified without touching real Ollama or MCP.

Uses a ``StubAgent`` injected via the ``agent_factory=`` test seam to
exercise every path through :func:`run_task` / :func:`run_eval`. The
real Agent is too heavy to spin up per test and pulls in Ollama as a
hard dependency for the path under test; the seam makes the runner
itself unit-testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from athena.eval.agent.runner import run_eval, run_task
from athena.eval.agent.task import EvalTask, VerifyContext


# ---------------------------------------------------------------------------
# Stub agent that the seam swaps in for the real one
# ---------------------------------------------------------------------------


class _Stats:
    def __init__(self) -> None:
        self.turns = 0
        self.tool_calls = 0
        self.eval_tokens = 0


class StubAgent:
    """Minimal Agent stand-in. Records calls; pretends to run."""

    def __init__(
        self,
        *,
        workspace: Path,
        on_run: Any = None,
        assistant_text: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
        raise_on_run: BaseException | None = None,
        sleep_on_run: float = 0.0,
    ) -> None:
        self.workspace = workspace
        self.stats = _Stats()
        self.messages = messages or []
        self.run_until_done_calls: list[str] = []
        self.closed = False
        self._on_run = on_run
        self._assistant_text = assistant_text
        self._tool_calls = tool_calls or []
        self._raise = raise_on_run
        self._sleep = sleep_on_run

    def run_until_done(self, user_prompt: str = "") -> None:
        self.run_until_done_calls.append(user_prompt)
        if self._sleep:
            import time as _t
            _t.sleep(self._sleep)
        if self._raise:
            raise self._raise
        # Pretend at least 1 turn happened so stats look real.
        self.stats.turns = 1
        if self._on_run:
            self._on_run(self.workspace)

    def last_assistant_message(self) -> str:
        return self._assistant_text

    def tool_call_trace(self) -> list[dict[str, Any]]:
        return self._tool_calls

    def close(self) -> None:
        self.closed = True


def _make_factory(**stub_kwargs: Any):
    """Build an agent_factory that returns a StubAgent with the
    given kwargs."""
    def _factory(*, workspace: Path, **_ignored: Any) -> StubAgent:
        return StubAgent(workspace=workspace, **stub_kwargs)
    return _factory


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_run_task_passes_when_verify_returns_true():
    task = EvalTask(
        id="t1",
        prompt="hello",
        setup_fn=lambda ws: (ws / "marker").write_text("x"),
        verify_fn=lambda ctx: (ctx.workspace / "marker").exists(),
        bucket="file_ops",
    )
    result = run_task(task, model="m", agent_factory=_make_factory())
    assert result.status == "passed"
    assert result.task_id == "t1"
    assert result.bucket == "file_ops"
    assert result.turns >= 1


def test_run_task_fails_when_verify_returns_false():
    task = EvalTask(
        id="t2",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: False,
    )
    result = run_task(task, model="m", agent_factory=_make_factory())
    assert result.status == "failed"


def test_run_task_records_assistant_excerpt():
    task = EvalTask(
        id="t3",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: True,
    )
    result = run_task(
        task,
        model="m",
        agent_factory=_make_factory(assistant_text="here is my answer"),
    )
    assert "here is my answer" in result.final_assistant_excerpt


# ---------------------------------------------------------------------------
# Isolation — each task gets its own tempdir
# ---------------------------------------------------------------------------


def test_each_task_gets_a_fresh_tempdir():
    seen_paths: list[Path] = []
    task = EvalTask(
        id="iso",
        prompt="...",
        setup_fn=lambda ws: seen_paths.append(ws),
        verify_fn=lambda ctx: True,
    )
    r1 = run_task(task, model="m", agent_factory=_make_factory())
    r2 = run_task(task, model="m", agent_factory=_make_factory())
    assert r1.status == "passed" and r2.status == "passed"
    assert seen_paths[0] != seen_paths[1]


def test_tempdir_cleaned_up_after_run():
    captured = {}
    task = EvalTask(
        id="cleanup",
        prompt="...",
        setup_fn=lambda ws: captured.setdefault("ws", ws),
        verify_fn=lambda ctx: True,
    )
    run_task(task, model="m", agent_factory=_make_factory())
    # TemporaryDirectory is removed on exit.
    assert not captured["ws"].exists()


# ---------------------------------------------------------------------------
# Error categories — verify the four-status taxonomy is honored
# ---------------------------------------------------------------------------


def test_setup_fn_raising_is_error_not_fail():
    """Bad test author setup => ERROR. The model never ran."""
    def _broken(ws):
        raise RuntimeError("setup broke")
    task = EvalTask(
        id="bad-setup",
        prompt="...",
        setup_fn=_broken,
        verify_fn=lambda ctx: True,  # never reached
    )
    result = run_task(task, model="m", agent_factory=_make_factory())
    assert result.status == "error"
    assert "setup broke" in result.error
    assert result.turns == 0  # agent never built


def test_agent_factory_raising_is_error():
    """Couldn't build the agent => ERROR, not fail."""
    def _bad_factory(**_):
        raise RuntimeError("no provider")
    task = EvalTask(
        id="no-agent",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: True,
    )
    result = run_task(task, model="m", agent_factory=_bad_factory)
    assert result.status == "error"
    assert "no provider" in result.error


def test_agent_raising_during_run_is_error():
    task = EvalTask(
        id="crash",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: True,
    )
    result = run_task(
        task,
        model="m",
        agent_factory=_make_factory(raise_on_run=RuntimeError("kaboom")),
    )
    assert result.status == "error"
    assert "kaboom" in result.error


def test_verify_fn_raising_is_failed_with_error_details():
    """A buggy verifier shouldn't crash the suite. Verify-raised is
    counted as FAIL (not ERROR — the model DID run), with the
    exception preserved in ``error`` for diagnosis."""
    def _bad_verify(ctx):
        raise ValueError("oops")
    task = EvalTask(
        id="bad-verify",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=_bad_verify,
    )
    result = run_task(task, model="m", agent_factory=_make_factory())
    assert result.status == "failed"
    assert "oops" in result.error


def test_timeout_is_its_own_status():
    """A hung task is failed-closed as TIMEOUT, not failed and not
    error — diagnosis needs the distinction."""
    task = EvalTask(
        id="hang",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: True,
        timeout_s=0.2,
    )
    result = run_task(
        task,
        model="m",
        agent_factory=_make_factory(sleep_on_run=1.0),
    )
    assert result.status == "timeout"
    assert "timeout_s" in result.error


# ---------------------------------------------------------------------------
# VerifyContext shape
# ---------------------------------------------------------------------------


def test_verify_context_exposes_workspace_and_messages():
    captured: dict[str, Any] = {}
    def _verify(ctx: VerifyContext) -> bool:
        captured["workspace"] = ctx.workspace
        captured["messages"] = ctx.agent_messages
        captured["tool_calls"] = ctx.tool_calls
        captured["mcp"] = ctx.mcp_call_log
        return True
    task = EvalTask(
        id="ctx",
        prompt="hi",
        setup_fn=lambda ws: None,
        verify_fn=_verify,
    )
    tools = [{"name": "Read", "args": {"file_path": "x"}}]
    msgs = [{"role": "user", "content": "hi"}]
    run_task(
        task,
        model="m",
        agent_factory=_make_factory(tool_calls=tools, messages=msgs),
    )
    assert captured["workspace"].name.startswith("athena-eval-")
    assert captured["tool_calls"] == tools
    assert captured["messages"] == msgs
    assert captured["mcp"] == []


# ---------------------------------------------------------------------------
# Lifecycle — close() always called
# ---------------------------------------------------------------------------


def test_agent_close_called_even_on_failure():
    instances: list[StubAgent] = []
    def _factory(*, workspace, **_):
        a = StubAgent(workspace=workspace, raise_on_run=RuntimeError("x"))
        instances.append(a)
        return a
    task = EvalTask(
        id="close-on-fail",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: True,
    )
    run_task(task, model="m", agent_factory=_factory)
    assert instances[0].closed is True


# ---------------------------------------------------------------------------
# Aggregate (run_eval)
# ---------------------------------------------------------------------------


def _trivial_task(task_id: str, *, passes: bool, bucket: str = "general") -> EvalTask:
    return EvalTask(
        id=task_id,
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: passes,
        bucket=bucket,
    )


def test_run_eval_aggregates_pass_rate():
    tasks = [
        _trivial_task("a", passes=True),
        _trivial_task("b", passes=True),
        _trivial_task("c", passes=False),
        _trivial_task("d", passes=False),
    ]
    report = run_eval(tasks, model="m", agent_factory=_make_factory())
    assert report.total == 4
    assert report.passed == 2
    assert report.failed == 2
    assert report.pass_rate == 0.5


def test_run_eval_records_per_bucket_stats():
    tasks = [
        _trivial_task("a1", passes=True, bucket="file_ops"),
        _trivial_task("a2", passes=True, bucket="file_ops"),
        _trivial_task("b1", passes=False, bucket="shell"),
    ]
    report = run_eval(tasks, model="m", agent_factory=_make_factory())
    by_bucket = report.by_bucket()
    assert by_bucket["file_ops"]["passed"] == 2
    assert by_bucket["file_ops"]["pass_rate"] == 1.0
    assert by_bucket["shell"]["passed"] == 0
    assert by_bucket["shell"]["pass_rate"] == 0.0


def test_run_eval_progress_callback_fires_per_task():
    seen: list[str] = []
    tasks = [_trivial_task(f"t{i}", passes=True) for i in range(3)]
    run_eval(
        tasks,
        model="m",
        agent_factory=_make_factory(),
        on_progress=lambda msg: seen.append(msg),
    )
    assert len(seen) == 3
    assert seen[0].startswith("[1/3]")
    assert seen[2].startswith("[3/3]")


def test_run_eval_one_bad_task_does_not_kill_the_suite():
    """ERROR in task 2 must not skip tasks 3+."""
    def _factory_for_id(target_id: str):
        def _factory(*, workspace, **_):
            if target_id == "boom":
                raise RuntimeError("only this one")
            return StubAgent(workspace=workspace)
        return _factory

    # Build a single factory that crashes for one specific call.
    call_count = {"n": 0}
    def _factory(*, workspace, **_):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("targeted")
        return StubAgent(workspace=workspace)

    tasks = [_trivial_task("t1", passes=True), _trivial_task("t2", passes=True), _trivial_task("t3", passes=True)]
    report = run_eval(tasks, model="m", agent_factory=_factory)
    assert report.total == 3
    statuses = [r.status for r in report.results]
    assert statuses == ["passed", "error", "passed"]


# ---------------------------------------------------------------------------
# Policy config plumbing — verify it reaches the factory
# ---------------------------------------------------------------------------


def test_policy_config_is_passed_to_agent_factory():
    received: dict[str, Any] = {}
    def _factory(*, workspace, policy_config=None, **_):
        received["policy_config"] = policy_config
        return StubAgent(workspace=workspace)

    task = _trivial_task("pol", passes=True)
    run_task(
        task,
        model="m",
        policy_config={"policy": "heuristic"},
        agent_factory=_factory,
    )
    assert received["policy_config"] == {"policy": "heuristic"}


def test_required_tools_passed_through_to_factory():
    received: dict[str, Any] = {}
    def _factory(*, workspace, enabled_toolsets=None, **_):
        received["enabled_toolsets"] = enabled_toolsets
        return StubAgent(workspace=workspace)

    task = EvalTask(
        id="tools",
        prompt="...",
        setup_fn=lambda ws: None,
        verify_fn=lambda ctx: True,
        required_tools=["core", "shell"],
    )
    run_task(task, model="m", agent_factory=_factory)
    assert received["enabled_toolsets"] == ["core", "shell"]
