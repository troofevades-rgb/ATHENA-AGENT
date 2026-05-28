"""Agent capability eval runner.

Boots a real ``athena.agent.core.Agent`` programmatically per task,
runs the task to completion in a temp workspace, calls the task's
``verify_fn`` to decide pass/fail, records the result.

Test-seam: ``agent_factory=`` and ``mcp_starter=`` kwargs let unit
tests inject stubs so the runner itself can be exercised without
touching real Ollama or spawning real MCP servers.
"""

from __future__ import annotations

import dataclasses
import logging
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .report import EvalReport, TaskResult
from .task import EvalTask, VerifyContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent factory — the seam between the eval and the real Agent
# ---------------------------------------------------------------------------


def _default_agent_factory(
    *,
    workspace: Path,
    model: str,
    policy_config: dict[str, Any] | None = None,
    enabled_toolsets: list[str] | None = None,
) -> Any:
    """Build a real Agent in the given workspace.

    Imports deferred so the module loads in environments without
    ollama / network access (the test seam never reaches here).

    Note: AUTO_DENY is installed inside the worker thread by
    ``run_task`` (see below) — installing it here is wrong because
    ``threading.Thread`` does NOT propagate ContextVars to its target.
    A previous version set it on the eval main thread, where it had
    no effect inside the runner thread; tasks then blocked on stdin
    for any confirmation-required tool and got reported as "timeout"
    instead of "approval deadlock."
    """
    from athena.agent.core import Agent
    from athena.config import Config

    cfg = Config(model=model)
    cfg.profile = "default"
    # Disable noisy background subsystems for eval determinism.
    cfg.review.nudge_interval = 0
    if enabled_toolsets:
        cfg.enabled_toolsets = list(enabled_toolsets)
    if policy_config is not None:
        cfg.parseltongue = dict(policy_config)

    return Agent(cfg, workspace, model=model)


# Type aliases that document the seam.
AgentFactory = Callable[..., Any]
MCPStarter = Callable[[Path, Iterable[Callable[[Path], Any]]], list[Any]]


# ---------------------------------------------------------------------------
# Running one task
# ---------------------------------------------------------------------------


def run_task(
    task: EvalTask,
    *,
    model: str,
    policy_config: dict[str, Any] | None = None,
    agent_factory: AgentFactory | None = None,
    mcp_starter: MCPStarter | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> TaskResult:
    """Run ``task`` against a fresh Agent in an isolated tempdir.

    Returns a ``TaskResult`` regardless of outcome — exceptions are
    captured and surfaced as ``status="error"`` so the suite never
    crashes on a single bad task.

    Parameters:
      - ``model``: model tag to pass to the agent factory.
      - ``policy_config``: dict matching the ``[parseltongue]`` config
        section (e.g. ``{"policy": "static", "defaults": {}}``).
        ``None`` defaults to athena's normal config.
      - ``agent_factory``: test seam. Default builds a real Agent.
      - ``mcp_starter``: test seam for MCP-bucket tasks. Default
        runs each factory in ``task.mcp_servers`` to start mock
        servers in the workspace.
      - ``on_progress``: optional ``(message: str) -> None`` for
        progress lines (e.g. CLI status updates).
    """
    factory = agent_factory or _default_agent_factory
    started = time.time()

    with tempfile.TemporaryDirectory(prefix="athena-eval-") as td:
        workspace = Path(td)

        # 1) Setup. setup_fn populates the workspace before the agent
        #    is constructed. If it raises, count as ERROR (not failed)
        #    — the test author's setup is broken; the model never got
        #    a chance to do anything.
        try:
            task.setup_fn(workspace)
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                bucket=task.bucket,
                status="error",
                duration_s=time.time() - started,
                error=f"setup_fn raised: {type(e).__name__}: {e}",
            )

        # 2) Spin up any mock MCP servers the task needs.
        mcp_call_log: list[dict[str, Any]] = []
        mcp_handles: list[Any] = []
        if task.mcp_servers:
            try:
                starter = mcp_starter or _start_mcp_servers
                mcp_handles = starter(workspace, task.mcp_servers)
                # Each handle exposes a ``call_log`` attribute (a
                # live reference; verify_fn reads it after the run).
                for h in mcp_handles:
                    if hasattr(h, "call_log"):
                        mcp_call_log = h.call_log  # last wins; tasks
                        # with multiple servers should use a verify_fn
                        # that walks ``ctx.workspace`` for richer state.
            except Exception as e:
                return TaskResult(
                    task_id=task.id,
                    bucket=task.bucket,
                    status="error",
                    duration_s=time.time() - started,
                    error=f"mcp setup raised: {type(e).__name__}: {e}",
                )

        # 3) Build the agent.
        agent: Any | None = None
        try:
            agent = factory(
                workspace=workspace,
                model=model,
                policy_config=policy_config,
                enabled_toolsets=task.required_tools or None,
            )
        except Exception as e:
            _shutdown_mcp(mcp_handles)
            return TaskResult(
                task_id=task.id,
                bucket=task.bucket,
                status="error",
                duration_s=time.time() - started,
                error=f"agent factory raised: {type(e).__name__}: {e}",
            )

        # 4) Run the task under a hard timeout. A hung task is failed
        #    closed without blocking the rest of the suite.
        status_holder: dict[str, Any] = {"done": False, "exc": None}

        def _runner() -> None:
            # AUTO_DENY MUST be installed inside this thread, not on
            # the eval main thread: threading.Thread does not propagate
            # ContextVars to its target. Without this, a task whose
            # agent calls a confirmation-required tool would block on
            # the default interactive callback (stdin), then trip the
            # worker.join timeout and be misreported as "timeout"
            # instead of "approval deadlock."
            from athena.safety.approval_callback import (
                AUTO_DENY,
                reset_approval_callback,
                set_approval_callback,
            )

            approval_token = set_approval_callback(AUTO_DENY)
            try:
                agent.run_until_done(task.prompt)
                status_holder["done"] = True
            except BaseException as e:  # noqa: BLE001
                status_holder["exc"] = e
            finally:
                reset_approval_callback(approval_token)

        worker = threading.Thread(
            target=_runner,
            name=f"eval-task-{task.id}",
            daemon=True,
        )
        if on_progress:
            try:
                on_progress(f"running task {task.id}")
            except Exception:
                pass
        worker.start()
        worker.join(timeout=task.timeout_s)

        run_duration = time.time() - started

        timed_out = worker.is_alive()
        # NOTE: daemon=True so the OS will reap the thread on
        # process exit. We can't synchronously kill a Python
        # thread mid-run; the timeout marker is the most we
        # can offer without C-level signals. In practice the
        # agent's own per-tool timeouts will cause it to
        # surrender eventually.

        # Snapshot stats BEFORE close (close may reset them on some paths).
        turns = getattr(getattr(agent, "stats", None), "turns", 0)
        eval_tokens = getattr(getattr(agent, "stats", None), "eval_tokens", 0)
        tool_calls_count = getattr(
            getattr(agent, "stats", None), "tool_calls", 0
        )
        # Tool call trace (per-call breakdown), separate from the
        # count metric.
        try:
            tool_calls = agent.tool_call_trace()
        except Exception:
            tool_calls = []
        try:
            final_text = agent.last_assistant_message()
        except Exception:
            final_text = ""
        messages = list(getattr(agent, "messages", []))

        # 5) Tear down.
        try:
            agent.close()
        except Exception:
            pass
        _shutdown_mcp(mcp_handles)

        # 6) Decide status.
        if timed_out:
            return TaskResult(
                task_id=task.id,
                bucket=task.bucket,
                status="timeout",
                duration_s=run_duration,
                turns=turns,
                tool_calls=tool_calls_count,
                eval_tokens=eval_tokens,
                error=f"task exceeded timeout_s={task.timeout_s}s",
                final_assistant_excerpt=_excerpt(final_text),
            )

        if status_holder["exc"] is not None:
            exc = status_holder["exc"]
            return TaskResult(
                task_id=task.id,
                bucket=task.bucket,
                status="error",
                duration_s=run_duration,
                turns=turns,
                tool_calls=tool_calls_count,
                eval_tokens=eval_tokens,
                error=f"agent raised: {type(exc).__name__}: {exc}",
                final_assistant_excerpt=_excerpt(final_text),
            )

        # 7) Verify. verify_fn raising is treated as FAIL with the
        #    exception in ``error`` so the suite continues. Use
        #    error= to distinguish "verifier said no" from "verifier
        #    crashed evaluating."
        ctx = VerifyContext(
            workspace=workspace,
            agent_messages=messages,
            tool_calls=tool_calls,
            mcp_call_log=list(mcp_call_log),
        )
        try:
            ok = bool(task.verify_fn(ctx))
            verify_error = ""
        except Exception as e:
            ok = False
            verify_error = (
                f"verify_fn raised: {type(e).__name__}: {e}\n"
                + traceback.format_exc(limit=3)
            )

        return TaskResult(
            task_id=task.id,
            bucket=task.bucket,
            status="passed" if ok else "failed",
            duration_s=run_duration,
            turns=turns,
            tool_calls=tool_calls_count,
            eval_tokens=eval_tokens,
            error=verify_error,
            final_assistant_excerpt=_excerpt(final_text),
        )


# ---------------------------------------------------------------------------
# Running an eval (a list of tasks)
# ---------------------------------------------------------------------------


def run_eval(
    tasks: list[EvalTask],
    *,
    model: str,
    policy_config: dict[str, Any] | None = None,
    task_set_name: str = "custom",
    agent_factory: AgentFactory | None = None,
    mcp_starter: MCPStarter | None = None,
    on_task_done: Callable[[TaskResult], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> EvalReport:
    """Run every task in ``tasks`` sequentially. Returns the
    aggregate ``EvalReport``."""
    started = time.time()
    results: list[TaskResult] = []
    for i, task in enumerate(tasks, start=1):
        if on_progress:
            try:
                on_progress(f"[{i}/{len(tasks)}] {task.id} ({task.bucket})")
            except Exception:
                pass
        result = run_task(
            task,
            model=model,
            policy_config=policy_config,
            agent_factory=agent_factory,
            mcp_starter=mcp_starter,
        )
        results.append(result)
        if on_task_done:
            try:
                on_task_done(result)
            except Exception:
                pass

    finished = time.time()
    policy_label = (
        (policy_config or {}).get("policy", "default")
        if policy_config is not None
        else "default"
    )
    return EvalReport(
        model=model,
        policy=str(policy_label),
        task_set=task_set_name,
        started_at=started,
        finished_at=finished,
        results=results,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _excerpt(text: str, limit: int = 400) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _start_mcp_servers(
    workspace: Path, factories: Iterable[Callable[[Path], Any]]
) -> list[Any]:
    """Default mock-MCP starter. Each factory is a callable that
    takes the workspace and returns a server handle. The handle is
    expected to be self-contained; the runner only retains references
    to call ``close()`` on each at task teardown."""
    handles: list[Any] = []
    for fac in factories:
        handles.append(fac(workspace))
    return handles


def _shutdown_mcp(handles: list[Any]) -> None:
    for h in handles:
        try:
            close = getattr(h, "close", None)
            if callable(close):
                close()
        except Exception:
            pass


__all__ = [
    "run_task",
    "run_eval",
    "AgentFactory",
    "MCPStarter",
]
