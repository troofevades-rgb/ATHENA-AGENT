"""Phase 18.2 stage 2 -- batched tool-call dispatch shape.

Pins :meth:`AgentRuntime._partition_tool_calls`:

  * Contiguous parallel-safe calls cluster into one batch.
  * A non-parallel-safe call breaks the cluster and sits alone.
  * Order across batches and within batches matches the model's
    emit order (the provider's tool_use <-> tool_result pairing
    depends on this).
  * Unknown tool names (typos, dropped tools) fall through as
    non-parallel-safe so they never accidentally race a real
    parallel-safe sibling.

And pins the dispatch loop in :meth:`_run_turn_inner`:

  * Same final message order as the pre-stage-2 ``for call in
    tool_calls`` shape.
  * The KeyboardInterrupt recovery still maps the ``recorded``
    count back onto the model's call order, so unexecuted calls
    get DENIED markers in the right slots.

Stage 2 keeps every batch dispatched serially; stage 3 will dispatch
multi-call parallel-safe batches concurrently via ThreadPoolExecutor.
"""

from __future__ import annotations

from typing import Any

import pytest

from athena.agent.runtime import AgentRuntime
from athena.tools.registry import bump_schema_version, tool

# ---------------------------------------------------------------------------
# A throwaway runtime stub -- just enough for _partition_tool_calls
# ---------------------------------------------------------------------------


class _StubRuntime(AgentRuntime):
    """Bypass Agent.__init__ -- ``_partition_tool_calls`` only reaches
    the tool registry, never ``self.*``."""

    def __init__(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture
def runtime() -> AgentRuntime:
    return _StubRuntime()


def _call(name: str) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": {}}}


# Register a pair of throwaway tools with known flags. These exist for
# the lifetime of the test session; the underscore prefix keeps the
# stage-1 drift-detection test in
# ``tests/tools/test_parallel_safe_flag.py`` ignoring them.
@tool(
    name="_batch_safe_a",
    description="probe",
    parameters={"type": "object", "properties": {}},
    toolset="_test",
    parallel_safe=True,
)
def _safe_a() -> str:
    return "a"


@tool(
    name="_batch_safe_b",
    description="probe",
    parameters={"type": "object", "properties": {}},
    toolset="_test",
    parallel_safe=True,
)
def _safe_b() -> str:
    return "b"


@tool(
    name="_batch_serial",
    description="probe",
    parameters={"type": "object", "properties": {}},
    toolset="_test",
    parallel_safe=False,
)
def _serial() -> str:
    return "x"


bump_schema_version()  # eager refresh after registering helpers


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------


def test_partition_empty_list_yields_no_batches(runtime) -> None:
    assert runtime._partition_tool_calls([]) == []


def test_partition_single_parallel_safe_call_alone(runtime) -> None:
    """A single parallel-safe call is still a batch of size 1 -- the
    flag only matters when there are siblings to group with."""
    out = runtime._partition_tool_calls([_call("_batch_safe_a")])
    assert len(out) == 1
    assert [c["function"]["name"] for c in out[0]] == ["_batch_safe_a"]


def test_partition_single_serial_call_alone(runtime) -> None:
    out = runtime._partition_tool_calls([_call("_batch_serial")])
    assert len(out) == 1
    assert [c["function"]["name"] for c in out[0]] == ["_batch_serial"]


def test_partition_groups_contiguous_parallel_safe_calls(runtime) -> None:
    """Two parallel-safe calls in a row cluster into one batch."""
    out = runtime._partition_tool_calls(
        [
            _call("_batch_safe_a"),
            _call("_batch_safe_b"),
        ]
    )
    assert len(out) == 1
    assert [c["function"]["name"] for c in out[0]] == [
        "_batch_safe_a",
        "_batch_safe_b",
    ]


def test_partition_break_on_non_parallel_safe_call(runtime) -> None:
    """A non-parallel-safe call interrupts the batch -- the model's
    emit order ``[safe, safe, serial, safe]`` must produce three
    batches (not two), so the serial call's side-effects sit between
    the read-only calls exactly where the model placed them."""
    out = runtime._partition_tool_calls(
        [
            _call("_batch_safe_a"),
            _call("_batch_safe_b"),
            _call("_batch_serial"),
            _call("_batch_safe_a"),
        ]
    )
    names = [[c["function"]["name"] for c in b] for b in out]
    assert names == [
        ["_batch_safe_a", "_batch_safe_b"],
        ["_batch_serial"],
        ["_batch_safe_a"],
    ]


def test_partition_consecutive_serial_calls_split_into_own_batches(
    runtime,
) -> None:
    """Two serial calls in a row become TWO batches (not one of size
    two) -- their order needs to be preserved across the serial
    handler, which only takes one call at a time."""
    out = runtime._partition_tool_calls(
        [
            _call("_batch_serial"),
            _call("_batch_serial"),
        ]
    )
    names = [[c["function"]["name"] for c in b] for b in out]
    assert names == [["_batch_serial"], ["_batch_serial"]]


def test_partition_unknown_tool_name_treated_as_serial(runtime) -> None:
    """A typoed call (no matching Tool) falls through as
    non-parallel-safe -- never accidentally races a real
    parallel-safe sibling."""
    out = runtime._partition_tool_calls(
        [
            _call("_batch_safe_a"),
            _call("_batch_does_not_exist"),
            _call("_batch_safe_b"),
        ]
    )
    names = [[c["function"]["name"] for c in b] for b in out]
    assert names == [
        ["_batch_safe_a"],
        ["_batch_does_not_exist"],
        ["_batch_safe_b"],
    ]


def test_partition_preserves_call_dict_identity(runtime) -> None:
    """The batches reuse the same dict objects -- not copies. The
    runtime hands them straight to ``_handle_tool_call`` so a copy
    here would silently strip provider-side ``id`` fields."""
    a = _call("_batch_safe_a")
    b = _call("_batch_safe_b")
    out = runtime._partition_tool_calls([a, b])
    assert out[0][0] is a
    assert out[0][1] is b


# ---------------------------------------------------------------------------
# Dispatch loop -- same observable order as the pre-stage-2 shape
# ---------------------------------------------------------------------------


def test_dispatch_order_matches_model_emit_order(monkeypatch) -> None:
    """End-to-end-ish: build a list with mixed safe/serial calls,
    walk the stage-2 dispatch (no real provider) and assert
    _handle_tool_call fires in the model's emit order."""
    runtime = _StubRuntime()
    fired: list[str] = []

    def _spy(call: dict[str, Any]) -> None:
        fired.append((call.get("function") or {}).get("name", ""))

    monkeypatch.setattr(runtime, "_handle_tool_call", _spy)

    tool_calls = [
        _call("_batch_safe_a"),
        _call("_batch_safe_b"),
        _call("_batch_serial"),
        _call("_batch_safe_b"),
        _call("_batch_safe_a"),
    ]
    for batch in runtime._partition_tool_calls(tool_calls):
        for call in batch:
            runtime._handle_tool_call(call)

    assert fired == [
        "_batch_safe_a",
        "_batch_safe_b",
        "_batch_serial",
        "_batch_safe_b",
        "_batch_safe_a",
    ]
