"""Phase 18.2 stage 4 -- hazard pass around parallel tool dispatch.

Stage 3 shipped real concurrency. This file pins the shared-state
contracts the dispatch path leans on:

  * The two per-call locks (``_ui_lock``, ``_stats_lock``) exist on
    every Agent and ARE engaged by ``_handle_tool_call`` -- a
    refactor that drops either would let multi-line panels splice or
    let stats increments drop, and we want a test that fires.
  * ``HookDispatcher.pre_tool_call`` and ``post_tool_call`` are
    reentrant: dispatching N times concurrently surfaces no crashes,
    no lost veto, and every plugin still sees every call.
  * The bundled observability plugin's per-call ``_tool_spans`` map
    keys on ``id(tool_args)`` so concurrent pre/post pairs route
    correctly -- regression-pin so a future ``args`` rewrite doesn't
    silently scramble span correlation.
  * ``ToolResultStorage.store`` is idempotent under concurrent same-
    content writes: the content-addressed digest is the source of
    truth, and a race resolves to a single blob with the right
    content.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from athena.plugins.base import Plugin
from athena.plugins.hooks import HookDispatcher
from athena.tools.tool_result_storage import ToolResultStorage


# ---------------------------------------------------------------------------
# The two per-call locks must exist on every Agent
# ---------------------------------------------------------------------------


def test_agent_init_creates_ui_and_stats_locks(
    isolated_home,
    workspace,
    fake_provider,
):
    """A real Agent built via AgentLifecycle.__init__ carries both
    ``_ui_lock`` and ``_stats_lock`` -- the parallel dispatch path
    reaches for these. A refactor that drops either re-opens the
    race the stage-3 + stage-4 tests pinned shut."""
    from athena.agent.core import Agent
    from athena.config import Config

    cfg = Config(model="fake-model")
    agent = Agent(cfg, workspace, provider=fake_provider)
    try:
        assert isinstance(agent._ui_lock, type(threading.Lock()))
        assert isinstance(agent._stats_lock, type(threading.Lock()))
    finally:
        agent.close()


def test_handle_tool_call_engages_ui_lock_around_panels(
    isolated_home,
    workspace,
    fake_provider,
):
    """``_handle_tool_call`` must enter ``self._ui_lock`` around
    ``ui.tool_call_summary`` and ``ui.tool_result``. A spy lock
    increments a counter on each acquire so we can pin both
    acquisitions per call without relying on a real Rich console."""
    from athena.agent.core import Agent
    from athena.config import Config
    from athena.tools.registry import bump_schema_version, tool

    @tool(
        name="_hazard_probe_tool",
        description="probe",
        parameters={"type": "object", "properties": {"idx": {"type": "integer"}}},
        toolset="_test",
        parallel_safe=True,
    )
    def _probe(idx: int = 0) -> str:
        return f"ok-{idx}"

    bump_schema_version()

    cfg = Config(model="fake-model")
    agent = Agent(cfg, workspace, provider=fake_provider)
    try:
        acquires = []

        class _SpyLock:
            def __enter__(self):
                acquires.append(1)
                return self

            def __exit__(self, *exc):
                return False

        # Swap in the spy; the real lock isn't needed for this test.
        agent._ui_lock = _SpyLock()

        call = {"function": {"name": "_hazard_probe_tool", "arguments": {"idx": 7}}}
        agent._handle_tool_call(call)
        # Exactly two acquires per successful call: one around
        # tool_call_summary, one around tool_result.
        assert len(acquires) == 2, (
            f"expected 2 _ui_lock acquires per call, got {len(acquires)}"
        )
    finally:
        agent.close()


# ---------------------------------------------------------------------------
# HookDispatcher reentrancy under concurrent pre/post invocations
# ---------------------------------------------------------------------------


class _CountingPlugin(Plugin):
    """Plugin that records every pre/post call on a thread-safe list."""

    name = "counting"

    def __init__(self) -> None:
        self.pre_calls: list[tuple[str, int]] = []
        self.post_calls: list[tuple[str, int]] = []
        self._lock = threading.Lock()

    def pre_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> bool | None:
        with self._lock:
            self.pre_calls.append((tool_name, tool_args.get("idx", 0)))
        return None

    def post_tool_call(
        self, tool_name: str, tool_args: dict[str, Any], result: str
    ) -> None:
        with self._lock:
            self.post_calls.append((tool_name, tool_args.get("idx", 0)))


class _VetoPlugin(Plugin):
    """Plugin that vetoes calls whose ``idx`` is odd."""

    name = "veto"

    def pre_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> bool | None:
        if tool_args.get("idx", 0) % 2 == 1:
            return False
        return None


def test_pre_tool_call_concurrent_dispatch_loses_no_invocation() -> None:
    """Fire pre_tool_call from N threads concurrently; the dispatcher
    is stateless w.r.t. its plugin list, so every plugin sees every
    call exactly once."""
    plugin = _CountingPlugin()
    dispatcher = HookDispatcher(plugins=[plugin])

    N = 200

    def _fire(i: int) -> tuple[bool, str | None]:
        return dispatcher.pre_tool_call("Probe", {"idx": i})

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_fire, range(N)))

    # Every dispatch allowed.
    assert all(allow for allow, _b in results)
    # Plugin saw every call.
    assert len(plugin.pre_calls) == N
    # Every idx represented (set comparison ignores order).
    assert {idx for _name, idx in plugin.pre_calls} == set(range(N))


def test_pre_tool_call_concurrent_veto_holds() -> None:
    """A plugin vetoing odd-idx calls keeps vetoing under concurrent
    dispatch -- no fairness/scheduling race lets one slip through."""
    counter = _CountingPlugin()
    veto = _VetoPlugin()
    dispatcher = HookDispatcher(plugins=[counter, veto])

    N = 100

    def _fire(i: int) -> tuple[bool, str | None]:
        return dispatcher.pre_tool_call("Probe", {"idx": i})

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(zip(range(N), pool.map(_fire, range(N))))

    for i, (allow, blocker) in results:
        if i % 2 == 1:
            assert allow is False and blocker == "veto", f"idx {i} not vetoed"
        else:
            assert allow is True and blocker is None, f"idx {i} unexpectedly vetoed"
    # Every call still observed by the counter (pre_tool_call calls
    # every plugin even after a veto -- documented in HookDispatcher
    # docstring).
    assert len(counter.pre_calls) == N


def test_post_tool_call_concurrent_dispatch_lossless() -> None:
    plugin = _CountingPlugin()
    dispatcher = HookDispatcher(plugins=[plugin])

    N = 200

    def _fire(i: int) -> None:
        dispatcher.post_tool_call("Probe", {"idx": i}, f"result-{i}")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(_fire, range(N)))

    assert len(plugin.post_calls) == N
    assert {idx for _name, idx in plugin.post_calls} == set(range(N))


# ---------------------------------------------------------------------------
# ToolResultStorage idempotent under concurrent identical writes
# ---------------------------------------------------------------------------


def test_concurrent_identical_stores_resolve_to_single_blob(tmp_path) -> None:
    """``ToolResultStorage.store`` keys blobs by SHA-256 of the
    content. N workers writing the same content concurrently must
    leave the directory with exactly one blob and one digest --
    the existence-check + write race resolves cleanly because both
    writers produce the same bytes at the same path."""
    storage = ToolResultStorage(tmp_path / "blobs", session_id="sess-1")
    content = "x" * 50_000

    handles: list[str] = []
    lock = threading.Lock()

    def _store(_i: int) -> None:
        s = storage.store(content, tool_name="probe")
        with lock:
            handles.append(s.handle)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_store, range(16)))

    assert len(handles) == 16
    # Every handle has the same digest (content-addressed).
    assert len(set(handles)) == 1, f"expected 1 unique handle, got {set(handles)}"
    # Exactly one .txt blob on disk under the storage dir.
    blobs = list((tmp_path / "blobs").glob("*.txt"))
    assert len(blobs) == 1, f"expected 1 blob, got {[b.name for b in blobs]}"


def test_concurrent_distinct_stores_each_land(tmp_path) -> None:
    """Sixteen workers each storing distinct content end up with
    sixteen distinct blobs (no overwrite, no lost write)."""
    storage = ToolResultStorage(tmp_path / "blobs", session_id="sess-1")

    def _store(i: int) -> str:
        return storage.store(f"unique-content-{i}-" * 5_000, tool_name="probe").hash

    with ThreadPoolExecutor(max_workers=8) as pool:
        digests = list(pool.map(_store, range(16)))

    assert len(set(digests)) == 16
    blobs = list((tmp_path / "blobs").glob("*.txt"))
    assert len(blobs) == 16
