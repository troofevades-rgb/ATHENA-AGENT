"""ApprovalRouter — async/sync bridge for dangerous-tool approvals.

The router exists to thread three pieces together:

1. The agent's *sync* approval callback (called from a worker thread).
2. The asyncio event loop (where the daemon and adapters run).
3. The adapter's button-click handler (also in the loop).

These tests verify each path: the async-side request, the
cross-thread sync bridge, the renderer contract, timeout-as-deny
fallback, and the late-click / unknown-id / cancel_all edge cases.
"""
from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from athena.gateway.approval_routing import ApprovalRouter
from athena.gateway.events import ApprovalRequest


# ---- async path -------------------------------------------------------


async def test_request_async_resolves_to_allow_when_user_allows() -> None:
    router = ApprovalRouter()
    seen_request_ids: list[str] = []

    async def renderer(req: ApprovalRequest) -> None:
        seen_request_ids.append(req.request_id)
        # Simulate user clicking allow shortly after the prompt renders.
        asyncio.get_running_loop().call_soon(
            lambda: router.resolve(req.request_id, "allow")
        )

    router.set_renderer(renderer)
    decision = await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={"cmd": "ls"},
    )
    assert decision == "allow"
    assert len(seen_request_ids) == 1
    assert router.pending_count == 0


async def test_request_async_resolves_to_deny_when_user_denies() -> None:
    router = ApprovalRouter()

    async def renderer(req: ApprovalRequest) -> None:
        asyncio.get_running_loop().call_soon(
            lambda: router.resolve(req.request_id, "deny")
        )

    router.set_renderer(renderer)
    decision = await router.request_async(
        session_id="s1", tool_name="Write", tool_args={"path": "/etc/passwd"},
    )
    assert decision == "deny"


async def test_no_renderer_installed_auto_denies() -> None:
    router = ApprovalRouter()
    decision = await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    assert decision == "deny"


async def test_renderer_exception_auto_denies() -> None:
    router = ApprovalRouter()

    async def boom(_req: ApprovalRequest) -> None:
        raise RuntimeError("simulated platform send failure")

    router.set_renderer(boom)
    decision = await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    assert decision == "deny"


async def test_timeout_resolves_to_deny() -> None:
    router = ApprovalRouter(default_timeout=0.05)

    async def renderer(_req: ApprovalRequest) -> None:
        return None  # user never clicks

    router.set_renderer(renderer)
    decision = await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    assert decision == "deny"
    assert router.pending_count == 0


async def test_custom_per_request_timeout_overrides_default() -> None:
    router = ApprovalRouter(default_timeout=5.0)
    router.set_renderer(AsyncMock())

    decision = await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={}, timeout=0.05,
    )
    assert decision == "deny"


# ---- resolve edge cases ----------------------------------------------


async def test_resolve_returns_true_on_first_call_false_after() -> None:
    router = ApprovalRouter()
    resolved: list[bool] = []

    async def renderer(req: ApprovalRequest) -> None:
        loop = asyncio.get_running_loop()
        loop.call_soon(lambda: resolved.append(router.resolve(req.request_id, "allow")))
        # Second click from the user (e.g. they tapped allow twice).
        loop.call_soon(lambda: resolved.append(router.resolve(req.request_id, "allow")))

    router.set_renderer(renderer)
    await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    assert resolved == [True, False]


async def test_resolve_unknown_request_id_returns_false() -> None:
    router = ApprovalRouter()
    assert router.resolve("never-existed", "allow") is False


async def test_pending_request_returns_record() -> None:
    router = ApprovalRouter()
    saw: list[ApprovalRequest] = []

    async def renderer(req: ApprovalRequest) -> None:
        saw.append(req)
        # Mid-request, the record should be retrievable.
        assert router.pending_request(req.request_id) is req
        asyncio.get_running_loop().call_soon(
            lambda: router.resolve(req.request_id, "allow")
        )

    router.set_renderer(renderer)
    await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    # After resolution, the record is gone.
    assert router.pending_request(saw[0].request_id) is None


# ---- sync bridge -----------------------------------------------------


async def test_request_sync_bridges_into_loop() -> None:
    """The agent's worker thread calls request_sync; the daemon's loop
    runs the async side; the worker unblocks with the decision."""
    router = ApprovalRouter()
    loop = asyncio.get_running_loop()
    router.bind_loop(loop)

    async def renderer(req: ApprovalRequest) -> None:
        loop.call_soon(lambda: router.resolve(req.request_id, "allow"))

    router.set_renderer(renderer)

    result: list[str] = []

    def worker_thread() -> None:
        result.append(
            router.request_sync(
                session_id="s1", tool_name="Bash", tool_args={"cmd": "ls"},
            )
        )

    t = threading.Thread(target=worker_thread)
    t.start()
    # Yield control so the loop can service the cross-thread submission.
    while t.is_alive():
        await asyncio.sleep(0.01)
    t.join()

    assert result == ["allow"]


async def test_request_sync_without_loop_returns_deny() -> None:
    """If the daemon never started (no loop bound), request_sync from
    a tool call must auto-deny rather than block forever."""
    router = ApprovalRouter()
    # No bind_loop call.
    result = router.request_sync(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    assert result == "deny"


async def test_request_sync_timeout_returns_deny() -> None:
    router = ApprovalRouter(default_timeout=0.05)
    loop = asyncio.get_running_loop()
    router.bind_loop(loop)

    async def renderer(_req: ApprovalRequest) -> None:
        return None

    router.set_renderer(renderer)

    result: list[str] = []

    def worker() -> None:
        result.append(
            router.request_sync(session_id="s", tool_name="Bash", tool_args={})
        )

    t = threading.Thread(target=worker)
    t.start()
    while t.is_alive():
        await asyncio.sleep(0.01)
    t.join()
    assert result == ["deny"]


# ---- cancel_all -------------------------------------------------------


async def test_cancel_all_denies_pending() -> None:
    """Daemon shutdown denies every pending approval immediately so
    blocked worker threads unwind before pool eviction."""
    router = ApprovalRouter()
    pending_decisions: list[str] = []

    async def renderer(_req: ApprovalRequest) -> None:
        return None  # user won't click — we cancel instead

    router.set_renderer(renderer)

    async def one_request() -> None:
        pending_decisions.append(
            await router.request_async(
                session_id="s1", tool_name="Bash", tool_args={},
                timeout=30.0,
            )
        )

    t1 = asyncio.create_task(one_request())
    t2 = asyncio.create_task(one_request())
    await asyncio.sleep(0.01)  # let both register pending futures
    assert router.pending_count == 2

    router.cancel_all()
    await asyncio.gather(t1, t2)
    assert pending_decisions == ["deny", "deny"]


# ---- bookkeeping -----------------------------------------------------


async def test_request_records_answered_at_and_decision_on_resolve() -> None:
    router = ApprovalRouter()
    captured: list[ApprovalRequest] = []

    async def renderer(req: ApprovalRequest) -> None:
        captured.append(req)
        # Capture state before resolution.
        assert req.answered_at is None
        assert req.decision is None
        asyncio.get_running_loop().call_soon(
            lambda: router.resolve(req.request_id, "allow")
        )

    router.set_renderer(renderer)
    await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    record = captured[0]
    assert record.decision == "allow"
    assert record.answered_at is not None


async def test_request_records_timeout_decision() -> None:
    router = ApprovalRouter(default_timeout=0.05)
    captured: list[ApprovalRequest] = []

    async def renderer(req: ApprovalRequest) -> None:
        captured.append(req)

    router.set_renderer(renderer)
    await router.request_async(
        session_id="s1", tool_name="Bash", tool_args={},
    )
    assert captured[0].decision == "deny"
    assert captured[0].answered_at is not None
