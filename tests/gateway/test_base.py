"""GatewayAdapter base — handle_inbound orchestration.

Covers the four interesting paths through ``handle_inbound``:

1. Lock is free → spawn ``_process``.
2. Lock is held *and* heartbeat is stale → heal, then spawn.
3. Lock is held *and* heartbeat is fresh → enqueue on steer queue and
   send a busy ack.
4. ``_process`` itself is unimplemented in 10.1 and raises
   ``NotImplementedError`` — verified by letting the spawned task run.

A minimal in-test ``_FakeDaemon`` stands in for the real
:class:`GatewayDaemon`, which lands in Prompt 10.2.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from athena.gateway.base import GatewayAdapter
from athena.gateway.events import MessageEvent


# ---- test doubles -------------------------------------------------------


class _FakeRouter:
    """Returns a fixed session id for every event."""

    def __init__(self, session_id: str = "sess-1") -> None:
        self.session_id = session_id
        self.calls: list[MessageEvent] = []

    async def resolve(self, event: MessageEvent) -> str:
        self.calls.append(event)
        return self.session_id


class _FakeSteerQueue:
    def __init__(self) -> None:
        self.pushes: list[tuple[str, str]] = []

    def push(self, session_id: str, text: str) -> None:
        self.pushes.append((session_id, text))


class _FakeDaemon:
    """Just enough surface for GatewayAdapter.handle_inbound."""

    def __init__(self, *, session_id: str = "sess-1") -> None:
        self.router = _FakeRouter(session_id)
        self.locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.steer_queue = _FakeSteerQueue()


class _TestAdapter(GatewayAdapter):
    """Concrete adapter that records outbound calls."""

    name = "test"

    def __init__(self, daemon: _FakeDaemon) -> None:
        super().__init__(daemon)  # type: ignore[arg-type]
        self.started = False
        self.stopped = False
        self.sent_text: list[tuple[str, str]] = []
        self.sent_files: list[tuple[str, Path, str | None]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_text(self, chat_id: str, text: str) -> str:
        self.sent_text.append((chat_id, text))
        return "msg-1"

    async def send_file(
        self, chat_id: str, file_path: Path, caption: str | None = None
    ) -> str:
        self.sent_files.append((chat_id, file_path, caption))
        return "msg-1"


def _evt(**kwargs: Any) -> MessageEvent:
    base = dict(
        platform="test", chat_id="chat-1", user_id="user-1", text="hi"
    )
    base.update(kwargs)
    return MessageEvent(**base)  # type: ignore[arg-type]


# ---- tests --------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_free_lock_spawns_processing():
    """Lock is free → handle_inbound schedules ``_process`` as a task
    and returns immediately."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)

    # Replace _process with an AsyncMock so we can observe the spawn
    # without hitting the 10.1 NotImplementedError.
    process_mock = AsyncMock()
    adapter._process = process_mock  # type: ignore[assignment]

    await adapter.handle_inbound(_evt())
    # Yield once so the spawned task gets to run.
    await asyncio.sleep(0)

    process_mock.assert_awaited_once()
    assert daemon.router.calls[0].chat_id == "chat-1"
    assert daemon.steer_queue.pushes == []
    assert adapter.sent_text == []


@pytest.mark.asyncio
async def test_inbound_locked_fresh_heartbeat_queues_message():
    """Lock is held by a live (fresh-heartbeat) task → message lands on
    the steer queue and a busy ack goes back."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)

    lock = daemon.locks["sess-1"]
    await lock.acquire()
    adapter._heartbeat.mark("sess-1")  # fresh — not stale

    try:
        await adapter.handle_inbound(_evt(text="follow-up"))
    finally:
        lock.release()

    assert daemon.steer_queue.pushes == [("sess-1", "follow-up")]
    assert adapter.sent_text == [("chat-1", "_busy — queued your message_")]


@pytest.mark.asyncio
async def test_inbound_locked_stale_heartbeat_heals_then_spawns():
    """Lock is held but heartbeat is older than the threshold → heal
    the lock, then spawn ``_process``."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    process_mock = AsyncMock()
    adapter._process = process_mock  # type: ignore[assignment]

    lock = daemon.locks["sess-1"]
    await lock.acquire()

    # Force is_stale → True via a stub healer; matches what a >60s
    # heartbeat age would do without making the test sleep.
    adapter._stale_lock_healer.is_stale = lambda *_a, **_kw: True  # type: ignore[assignment]

    await adapter.handle_inbound(_evt())
    await asyncio.sleep(0)

    process_mock.assert_awaited_once()
    assert not lock.locked(), "healer should have released the lock"
    assert daemon.steer_queue.pushes == []


@pytest.mark.asyncio
async def test_process_is_not_implemented_in_10_1():
    """Confirms the stub: the abstract loop is not yet wired."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    lock = daemon.locks["sess-1"]
    with pytest.raises(NotImplementedError):
        await adapter._process(_evt(), "sess-1", lock)


@pytest.mark.asyncio
async def test_subclass_must_implement_abstract_methods():
    """``GatewayAdapter`` cannot be instantiated directly — Python's
    ABC machinery blocks it."""
    with pytest.raises(TypeError):
        GatewayAdapter(_FakeDaemon())  # type: ignore[abstract,arg-type]
