"""ContextVar-scoped approval grants (Phase 17.2)."""
from __future__ import annotations

import asyncio
import contextvars

import pytest

from athena.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    FOREGROUND,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety.approval_guard import (
    ApprovalDeniedInBackground,
    _approval_grants,
    current_grants,
    request_approval,
    reset_approvals,
    scope_fresh_approvals,
)


@pytest.fixture(autouse=True)
def _isolate_grants():
    """Each test starts with an empty grant cache."""
    token = _approval_grants.set({})
    try:
        yield
    finally:
        _approval_grants.reset(token)


# ---- foreground caching ----------------------------------------------------


async def test_foreground_caches_result_across_calls() -> None:
    """Same resource_id only calls the prompt once."""
    calls: list[str] = []

    async def prompt(resource_id: str) -> bool:
        calls.append(resource_id)
        return True

    origin = set_current_write_origin(FOREGROUND)
    try:
        first = await request_approval("file:/etc/hosts", prompt)
        second = await request_approval("file:/etc/hosts", prompt)
    finally:
        reset_current_write_origin(origin)

    assert first is True
    assert second is True
    assert calls == ["file:/etc/hosts"]


async def test_foreground_different_resources_each_prompted() -> None:
    seen: list[str] = []

    async def prompt(resource_id: str) -> bool:
        seen.append(resource_id)
        return True

    origin = set_current_write_origin(FOREGROUND)
    try:
        await request_approval("file:/a", prompt)
        await request_approval("file:/b", prompt)
    finally:
        reset_current_write_origin(origin)

    assert seen == ["file:/a", "file:/b"]


async def test_foreground_cached_false_does_not_reprompt() -> None:
    """Negative grants are remembered too — the user said no, don't ask again."""
    calls: list[str] = []

    async def prompt(resource_id: str) -> bool:
        calls.append(resource_id)
        return False

    origin = set_current_write_origin(FOREGROUND)
    try:
        first = await request_approval("file:/secrets", prompt)
        second = await request_approval("file:/secrets", prompt)
    finally:
        reset_current_write_origin(origin)

    assert first is False
    assert second is False
    assert calls == ["file:/secrets"]


# ---- background denial -----------------------------------------------------


async def test_background_raises_approval_denied() -> None:
    async def prompt(resource_id: str) -> bool:  # pragma: no cover
        raise AssertionError("prompt should never be invoked in background")

    origin = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        with pytest.raises(ApprovalDeniedInBackground) as ei:
            await request_approval("file:/etc/hosts", prompt)
    finally:
        reset_current_write_origin(origin)

    assert "background_review" in str(ei.value)
    assert "/etc/hosts" in str(ei.value)


async def test_curator_origin_also_denied() -> None:
    """All non-foreground origins behave the same."""
    async def prompt(resource_id: str) -> bool:  # pragma: no cover
        raise AssertionError("never called")

    origin = set_current_write_origin(CURATOR)
    try:
        with pytest.raises(ApprovalDeniedInBackground):
            await request_approval("file:/etc/hosts", prompt)
    finally:
        reset_current_write_origin(origin)


async def test_background_auto_approve_returns_true_without_prompt() -> None:
    async def prompt(resource_id: str) -> bool:  # pragma: no cover
        raise AssertionError("auto-approve must skip the prompt")

    origin = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        ok = await request_approval(
            "skill:demo", prompt, auto_approve_in_background=True,
        )
    finally:
        reset_current_write_origin(origin)
    assert ok is True


async def test_background_does_not_consult_foreground_cache() -> None:
    """A grant cached in foreground must not be visible to a background
    fork. The fork should always go through scope_fresh_approvals(); this
    test verifies the second line of defense — even without scoping, the
    code refuses to read the cache when origin != foreground."""
    async def yes(_: str) -> bool:
        return True

    foreground = set_current_write_origin(FOREGROUND)
    try:
        await request_approval("file:/x", yes)
        assert current_grants() == {"file:/x": True}
    finally:
        reset_current_write_origin(foreground)

    # Now switch to background WITHOUT re-scoping. The cached True must
    # not be honored.
    async def must_not_call(_: str) -> bool:  # pragma: no cover
        raise AssertionError("background must not consult foreground cache")

    background = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        with pytest.raises(ApprovalDeniedInBackground):
            await request_approval("file:/x", must_not_call)
    finally:
        reset_current_write_origin(background)


# ---- scope_fresh_approvals / reset_approvals ------------------------------


async def test_scope_fresh_isolates_then_restores() -> None:
    """scope_fresh_approvals() empties the cache; reset_approvals()
    brings the parent cache back."""
    async def yes(_: str) -> bool:
        return True

    origin = set_current_write_origin(FOREGROUND)
    try:
        await request_approval("file:/parent", yes)
        assert current_grants() == {"file:/parent": True}

        token = scope_fresh_approvals()
        try:
            assert current_grants() == {}
            await request_approval("file:/child", yes)
            assert current_grants() == {"file:/child": True}
        finally:
            reset_approvals(token)

        # Parent cache restored, child grant gone.
        assert current_grants() == {"file:/parent": True}
    finally:
        reset_current_write_origin(origin)


# ---- ContextVar concurrency isolation -------------------------------------


async def test_grants_do_not_leak_across_concurrent_tasks() -> None:
    """Approving one resource in one task must not be observable in
    another concurrent task. ContextVar provides per-task isolation
    when tasks are spawned via asyncio.create_task() — verify that."""
    barrier_a = asyncio.Event()
    barrier_b = asyncio.Event()

    captured_a: dict[str, bool] | None = None
    captured_b: dict[str, bool] | None = None

    async def task_a() -> None:
        nonlocal captured_a
        async def yes(_: str) -> bool:
            return True
        token = set_current_write_origin(FOREGROUND)
        try:
            await request_approval("resource:a", yes)
            barrier_a.set()
            await barrier_b.wait()
            captured_a = current_grants()
        finally:
            reset_current_write_origin(token)

    async def task_b() -> None:
        nonlocal captured_b
        async def yes(_: str) -> bool:
            return True
        token = set_current_write_origin(FOREGROUND)
        try:
            await barrier_a.wait()
            await request_approval("resource:b", yes)
            barrier_b.set()
            captured_b = current_grants()
        finally:
            reset_current_write_origin(token)

    # Wrap each task in its own copy of the current context so the
    # grants ContextVar can't leak across them.
    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    coros = [
        asyncio.ensure_future(ctx_a.run(asyncio.ensure_future, task_a())),
        asyncio.ensure_future(ctx_b.run(asyncio.ensure_future, task_b())),
    ]
    await asyncio.gather(*coros)

    assert captured_a == {"resource:a": True}
    assert captured_b == {"resource:b": True}


# ---- current_grants() returns a defensive copy ---------------------------


async def test_current_grants_returns_a_copy_not_the_live_dict() -> None:
    async def yes(_: str) -> bool:
        return True

    origin = set_current_write_origin(FOREGROUND)
    try:
        await request_approval("file:/x", yes)
        snap = current_grants()
        snap["forged"] = True  # mutate the returned dict
        # Internal state must not reflect the forged entry.
        assert "forged" not in current_grants()
    finally:
        reset_current_write_origin(origin)
