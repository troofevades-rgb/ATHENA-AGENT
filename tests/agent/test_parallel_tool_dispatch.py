"""Phase 18.2 stage 3 -- parallel tool dispatch via ThreadPoolExecutor.

Pins :meth:`AgentRuntime._dispatch_batch`:

  * ``cfg.parallel_tool_workers <= 1`` keeps the pre-stage-3 serial
    behaviour exactly -- never spins up a pool.
  * Multi-call parallel-safe batches with ``parallel_tool_workers >
    1`` dispatch concurrently AND record tool messages in the
    model's original call order (the provider's
    tool_use <-> tool_result pairing depends on it).
  * Worker threads inherit the foreground context via
    ``contextvars.copy_context()`` so per-session ContextVars (active
    agent, workspace, etc.) propagate.
  * The shared ``Stats.record_tool_call`` mutation is locked -- under
    concurrent dispatch every call increments the counter exactly
    once.

The dispatch path is exercised via a stub Agent built with
``__new__`` so we don't have to spin up a real provider. The stub
populates only the attributes ``_dispatch_batch`` and the parallel
branch of ``_handle_tool_call`` reach for.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from athena.agent.runtime import AgentRuntime
from athena.agent.stats import Stats
from athena.plugins.hooks import HookDispatcher
from athena.tools import thrash as _thrash
from athena.tools.registry import bump_schema_version, tool


@pytest.fixture(autouse=True)
def _reset_thrash_buffer() -> None:
    """The thrash detector deduplicates identical (tool, args) calls
    within a process. Many of these tests fire the same probe tool
    repeatedly; without a reset the third call hits the THRASH
    WARNING short-circuit instead of running the real implementation."""
    _thrash.reset()
    yield
    _thrash.reset()


# ---------------------------------------------------------------------------
# Stub Runtime -- skip __init__, populate only what _dispatch_batch /
# _handle_tool_call need.
# ---------------------------------------------------------------------------


def _make_stub(
    *,
    parallel_tool_workers: int = 1,
) -> AgentRuntime:
    rt = AgentRuntime.__new__(AgentRuntime)
    # Attributes _handle_tool_call reads.
    rt.cfg = SimpleNamespace(  # type: ignore[attr-defined]
        parallel_tool_workers=parallel_tool_workers,
        tool_call_sanitize=False,
        auto_approve_tools=True,
    )
    rt.stats = Stats()  # type: ignore[attr-defined]
    rt._stats_lock = threading.Lock()  # type: ignore[attr-defined]
    rt.messages = []  # type: ignore[attr-defined]
    rt.session_store = None  # type: ignore[attr-defined]
    rt.session_id = None  # type: ignore[attr-defined]
    rt.tool_result_storage = None  # type: ignore[attr-defined]
    rt.plugin_hooks = HookDispatcher(plugins=[])  # type: ignore[attr-defined]
    return rt


# ---------------------------------------------------------------------------
# Workhorse tools used by these tests -- registered once at module load.
# The leading underscore keeps stage-1's drift-detection test ignoring
# them.
# ---------------------------------------------------------------------------


# Probes take an ``idx`` so each call's args are unique -- otherwise
# the thrash detector short-circuits identical-args replays after the
# second one and the tool body never runs (which would invalidate the
# concurrency wall-clock test, the stats-counter test, and the
# context-propagation test).


@tool(
    name="_par_fast",
    description="instant return",
    parameters={
        "type": "object",
        "properties": {"idx": {"type": "integer"}},
    },
    toolset="_test",
    parallel_safe=True,
)
def _par_fast(idx: int = 0) -> str:
    return f"ok-fast-{idx}"


# A slow tool whose duration lets us prove parallelism wall-clock-wise:
# 4 calls × 0.20 s = 0.80 s serial; with 4 workers the wall-clock
# drops to ~0.20 s (each worker runs its sleep concurrently).
@tool(
    name="_par_slow",
    description="sleeps then returns",
    parameters={
        "type": "object",
        "properties": {"idx": {"type": "integer"}},
    },
    toolset="_test",
    parallel_safe=True,
)
def _par_slow(idx: int = 0) -> str:
    time.sleep(0.20)
    return f"ok-slow-{idx}"


bump_schema_version()


def _call(name: str, **args: Any) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": args}}


# ---------------------------------------------------------------------------
# Serial-preservation: parallel_tool_workers <= 1
# ---------------------------------------------------------------------------


def test_workers_one_uses_serial_path(monkeypatch) -> None:
    """``parallel_tool_workers = 1`` is the default and must dispatch
    every call serially via ``_handle_tool_call`` -- no thread pool
    spin-up, no contextvars.copy_context, no slot buffering."""
    rt = _make_stub(parallel_tool_workers=1)
    order: list[str] = []

    def _spy(call, *, record_sink=None):  # type: ignore[no-untyped-def]
        name = (call.get("function") or {}).get("name", "")
        order.append(name)
        # Pretend the serial path ran the real recorder.
        rt._record_tool_result(call, name, "ok")

    monkeypatch.setattr(rt, "_handle_tool_call", _spy)

    rt._dispatch_batch([_call("_par_fast", idx=0), _call("_par_fast", idx=1)])
    assert order == ["_par_fast", "_par_fast"]


def test_single_call_batch_never_uses_pool(monkeypatch) -> None:
    """Even with ``parallel_tool_workers = 4`` a batch of size 1 must
    go through the serial fast-path -- the pool would be pure
    overhead."""
    rt = _make_stub(parallel_tool_workers=4)

    used_sink: list[bool] = []

    def _spy(call, *, record_sink=None):  # type: ignore[no-untyped-def]
        # Serial path passes record_sink=None; parallel path passes
        # a non-None capture function.
        used_sink.append(record_sink is not None)
        rt._record_tool_result(call, "X", "ok")

    monkeypatch.setattr(rt, "_handle_tool_call", _spy)

    rt._dispatch_batch([_call("_par_fast", idx=0)])
    assert used_sink == [False]


# ---------------------------------------------------------------------------
# Parallel path: ordering, concurrency, ContextVar propagation
# ---------------------------------------------------------------------------


def test_parallel_dispatch_records_in_model_emit_order() -> None:
    """Four workers complete in non-deterministic finish order but the
    resulting tool messages MUST land in self.messages in the model's
    original call order. The provider's tool_use <-> tool_result
    pairing depends on this."""
    rt = _make_stub(parallel_tool_workers=4)
    batch = [_call("_par_fast", idx=i) for i in range(4)]
    # Tag each call with a unique id so we can verify the order in
    # the resulting tool messages.
    for i, c in enumerate(batch):
        c["id"] = f"call-{i}"
    rt._dispatch_batch(batch)
    ids_in_order = [m.get("tool_call_id") for m in rt.messages if m.get("role") == "tool"]
    assert ids_in_order == ["call-0", "call-1", "call-2", "call-3"]


def test_parallel_dispatch_actually_runs_concurrently() -> None:
    """A 4-call batch of 200ms-sleep tools finishes in well under the
    800ms a serial run would take -- proves the pool is doing real
    work, not just looping."""
    rt = _make_stub(parallel_tool_workers=4)
    batch = [_call("_par_slow", idx=i) for i in range(4)]

    t0 = time.monotonic()
    rt._dispatch_batch(batch)
    elapsed = time.monotonic() - t0

    # Pure-Python sleeps release the GIL; 4-way concurrency should
    # finish near 0.20 s. Give generous slack for CI noise.
    assert elapsed < 0.55, (
        f"4-call parallel batch took {elapsed:.2f}s -- serial would "
        f"take ~0.80s. Workers don't appear to be running concurrently."
    )
    # All four still recorded.
    assert len([m for m in rt.messages if m.get("role") == "tool"]) == 4


def test_stats_counter_locked_under_concurrent_dispatch() -> None:
    """``Stats.record_tool_call`` mutates a dict + an int non-atomically.
    Under concurrent dispatch the lock in ``_handle_tool_call`` ensures
    every call increments the counter exactly once."""
    rt = _make_stub(parallel_tool_workers=8)
    batch = [_call("_par_fast", idx=i) for i in range(50)]
    rt._dispatch_batch(batch)
    assert rt.stats.tool_calls == 50
    assert rt.stats.tool_call_counts.get("_par_fast") == 50


def test_contextvars_propagate_into_workers() -> None:
    """Workers inherit the foreground context via
    ``contextvars.copy_context()`` -- a tool that reads the
    ``_current_agent`` ContextVar should see the parent's agent
    (the stub itself, since that's what the test main thread sets)."""
    from athena.agent.context import _current_agent

    rt = _make_stub(parallel_tool_workers=4)

    seen_agents: list[Any] = []
    lock = threading.Lock()

    @tool(
        name="_par_ctx_probe",
        description="reads _current_agent",
        parameters={
            "type": "object",
            "properties": {"idx": {"type": "integer"}},
        },
        toolset="_test",
        parallel_safe=True,
    )
    def _probe(idx: int = 0) -> str:
        with lock:
            seen_agents.append(_current_agent.get())
        return f"ok-{idx}"

    bump_schema_version()

    token = _current_agent.set(rt)
    try:
        # Unique idx per call so the thrash detector doesn't
        # short-circuit identical-args replays.
        rt._dispatch_batch([_call("_par_ctx_probe", idx=i) for i in range(3)])
    finally:
        _current_agent.reset(token)

    assert len(seen_agents) == 3
    assert all(a is rt for a in seen_agents), (
        f"workers saw {seen_agents}, expected the parent stub agent. "
        "contextvars.copy_context() snapshot isn't propagating."
    )
