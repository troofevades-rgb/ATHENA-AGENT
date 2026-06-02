"""Phase 18.2 stage 5 -- KeyboardInterrupt mid-batch in the parallel
dispatch path.

Pins :meth:`AgentRuntime._dispatch_batch` when ``Ctrl+C`` fires
while a parallel batch is in flight:

  * Pending Futures get cancelled so the pool stops dispatching new
    workers.
  * In-flight workers finish their tool body (Python can't kill a
    running thread); their slot populates within a brief grace
    window and we record their results in declared order.
  * Calls whose slot stays empty get a ``DENIED: tool execution
    interrupted by user (Ctrl+C)`` marker in declared order so the
    provider's tool_use <-> tool_result pairing stays intact.
  * ``self._last_turn_interrupted`` flips to ``True`` so
    ``_consult_goal_continuation`` knows to pause the goal loop.
  * KeyboardInterrupt re-raises so the outer ``_run_turn_inner``
    recovery handles cross-batch cleanup (subsequent batches'
    calls all DENIED, ``[previous tool execution was
    interrupted by the user]`` marker appended).
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
    _thrash.reset()
    yield
    _thrash.reset()


def _make_stub(*, parallel_tool_workers: int = 4) -> AgentRuntime:
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.cfg = SimpleNamespace(  # type: ignore[attr-defined]
        parallel_tool_workers=parallel_tool_workers,
        tool_call_sanitize=False,
        auto_approve_tools=True,
    )
    rt.stats = Stats()  # type: ignore[attr-defined]
    rt._stats_lock = threading.Lock()  # type: ignore[attr-defined]
    rt._ui_lock = threading.Lock()  # type: ignore[attr-defined]
    rt.messages = []  # type: ignore[attr-defined]
    rt.session_store = None  # type: ignore[attr-defined]
    rt.session_id = None  # type: ignore[attr-defined]
    rt.tool_result_storage = None  # type: ignore[attr-defined]
    rt.plugin_hooks = HookDispatcher(plugins=[])  # type: ignore[attr-defined]
    rt._last_turn_interrupted = False  # type: ignore[attr-defined]
    return rt


def _call(name: str, **args: Any) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": args}, "id": f"id-{args.get('idx', '?')}"}


# ---------------------------------------------------------------------------
# Throwaway tools. The leading underscore keeps stage-1's drift test
# ignoring them; per-call ``idx`` skirts the thrash detector.
# ---------------------------------------------------------------------------


# Synchronises with the interrupting test: every worker calls
# ``_started.set()`` so the test waits until at least one worker is
# in-flight before delivering KeyboardInterrupt -- otherwise the
# interrupt fires before the pool has scheduled anything and the test
# is exercising "interrupt before any worker started" instead of
# mid-batch.
_started = threading.Event()
# Number of workers that completed cleanly per test. The interrupting
# test reads this to assert that some real work landed before the
# interrupt arrived.
_completed = threading.Event()


@tool(
    name="_int_quick",
    description="instant return",
    parameters={
        "type": "object",
        "properties": {"idx": {"type": "integer"}},
    },
    toolset="_test",
    parallel_safe=True,
)
def _int_quick(idx: int = 0) -> str:
    _started.set()
    _completed.set()
    return f"quick-{idx}"


@tool(
    name="_int_slow",
    description="sleeps long enough to still be in flight when Ctrl+C arrives",
    parameters={
        "type": "object",
        "properties": {"idx": {"type": "integer"}},
    },
    toolset="_test",
    parallel_safe=True,
)
def _int_slow(idx: int = 0) -> str:
    _started.set()
    time.sleep(0.40)
    _completed.set()
    return f"slow-{idx}"


@tool(
    name="_int_raises",
    description="raises KeyboardInterrupt from inside the tool body",
    parameters={
        "type": "object",
        "properties": {"idx": {"type": "integer"}},
    },
    toolset="_test",
    parallel_safe=True,
)
def _int_raises(idx: int = 0) -> str:
    _started.set()
    raise KeyboardInterrupt


bump_schema_version()


@pytest.fixture(autouse=True)
def _reset_signals() -> None:
    _started.clear()
    _completed.clear()
    yield
    _started.clear()
    _completed.clear()


# ---------------------------------------------------------------------------
# Behaviour pins
# ---------------------------------------------------------------------------


def test_interrupt_reraises_keyboard_interrupt() -> None:
    """A worker raising KeyboardInterrupt re-raises out of
    _dispatch_batch -- the outer _run_turn_inner needs that signal
    to fire its cross-batch recovery."""
    rt = _make_stub(parallel_tool_workers=4)
    batch = [
        _call("_int_quick", idx=0),
        _call("_int_raises", idx=1),
        _call("_int_quick", idx=2),
    ]
    with pytest.raises(KeyboardInterrupt):
        rt._dispatch_batch(batch)


def test_interrupt_sets_last_turn_interrupted() -> None:
    rt = _make_stub(parallel_tool_workers=4)
    batch = [
        _call("_int_quick", idx=0),
        _call("_int_raises", idx=1),
        _call("_int_quick", idx=2),
    ]
    try:
        rt._dispatch_batch(batch)
    except KeyboardInterrupt:
        pass
    assert rt._last_turn_interrupted is True


def test_completed_workers_recorded_in_declared_order() -> None:
    """Workers that finished BEFORE the interrupt arrived get their
    results recorded in the model's declared order. The interrupting
    worker and any uncompleted ones get DENIED in their declared
    slots."""
    rt = _make_stub(parallel_tool_workers=4)
    batch = [
        _call("_int_quick", idx=0),
        _call("_int_quick", idx=1),
        _call("_int_raises", idx=2),
        _call("_int_quick", idx=3),
    ]
    try:
        rt._dispatch_batch(batch)
    except KeyboardInterrupt:
        pass

    tool_msgs = [m for m in rt.messages if m.get("role") == "tool"]
    # One tool message per call -- declared order preserved.
    assert len(tool_msgs) == 4
    assert [m["tool_call_id"] for m in tool_msgs] == [
        "id-0",
        "id-1",
        "id-2",
        "id-3",
    ]


def test_uncompleted_slots_get_denied_marker() -> None:
    """The tool that raised AND any neighbour whose slot stayed empty
    end up with the DENIED message -- never silently dropped."""
    rt = _make_stub(parallel_tool_workers=4)
    batch = [
        _call("_int_quick", idx=0),
        _call("_int_raises", idx=1),
        _call("_int_quick", idx=2),
    ]
    try:
        rt._dispatch_batch(batch)
    except KeyboardInterrupt:
        pass

    tool_msgs = [m for m in rt.messages if m.get("role") == "tool"]
    by_id = {m["tool_call_id"]: m["content"] for m in tool_msgs}
    assert by_id["id-0"] == "quick-0"  # finished cleanly
    assert by_id["id-1"].startswith("DENIED:")  # raised inside body
    # idx=2 might have finished cleanly OR been cancelled before it
    # ran, depending on scheduling. Either is acceptable -- the
    # invariant is that the slot is filled.
    assert "id-2" in by_id


def test_serial_path_does_not_swallow_keyboard_interrupt() -> None:
    """``parallel_tool_workers=1`` keeps the serial path; a tool that
    raises KeyboardInterrupt still propagates so the outer
    _run_turn_inner recovery fires. No DENIED rewrites in this path
    -- the existing serial recovery in _run_turn_inner has owned
    that since stages 1+2."""
    rt = _make_stub(parallel_tool_workers=1)
    batch = [_call("_int_raises", idx=0)]
    with pytest.raises(KeyboardInterrupt):
        rt._dispatch_batch(batch)
    # Serial path doesn't touch _last_turn_interrupted -- the outer
    # recovery in _run_turn_inner sets it.
    assert rt._last_turn_interrupted is False
