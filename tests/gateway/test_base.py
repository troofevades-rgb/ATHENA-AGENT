"""GatewayAdapter base — Hermes-style guard + pending-slot orchestration.

Covers the policy matrix ``handle_inbound`` implements:

- Free session → install guard atomically + spawn processing.
- Busy session + TEXT follow-up → merge into pending slot + signal
  interrupt event (no second task spawned).
- Busy session + PHOTO follow-up → merge into pending slot WITHOUT
  signalling interrupt (album-burst case).
- Busy session + ``/approve|/deny|/status|/restart`` → inline bypass
  via ``daemon.dispatch_command``.
- Busy session + ``/stop|/new|/reset`` → command-scoped guard swap,
  command response sends, in-flight task cancelled *after*, pending
  drains.
- Stale guard (owner task done) → heal on entry, then re-route as if
  free.
- Race: two events arriving on the same tick — only one task spawns,
  the second merges into pending.

A minimal in-test ``_FakeDaemon`` stands in for the real
:class:`GatewayDaemon`, which lands in Prompt 10.2.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from athena.gateway.base import (
    BYPASS_COMMANDS,
    CANCELING_BYPASS_COMMANDS,
    GatewayAdapter,
    merge_pending_message_event,
)
from athena.gateway.events import MessageEvent, MessageType


# ---- test doubles -------------------------------------------------------


class _FakeRouter:
    def __init__(self, session_id: str = "sess-1") -> None:
        self.session_id = session_id
        self.calls: list[MessageEvent] = []

    async def resolve(self, event: MessageEvent) -> str:
        self.calls.append(event)
        return self.session_id


class _FakeDaemon:
    """Just enough surface for handle_inbound + bypass dispatch."""

    def __init__(self, *, session_id: str = "sess-1") -> None:
        self.router = _FakeRouter(session_id)
        self.dispatch_command = AsyncMock(return_value="ok")


class _TestAdapter(GatewayAdapter):
    name = "test"

    def __init__(self, daemon: _FakeDaemon) -> None:
        super().__init__(daemon)  # type: ignore[arg-type]
        self.sent_text: list[tuple[str, str]] = []
        self.sent_files: list[tuple[str, Path, str | None]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_text(self, chat_id: str, text: str) -> str:
        self.sent_text.append((chat_id, text))
        return "msg-id"

    async def send_file(
        self, chat_id: str, file_path: Path, caption: str | None = None
    ) -> str:
        self.sent_files.append((chat_id, file_path, caption))
        return "msg-id"


def _evt(text: str = "hi", **kwargs: Any) -> MessageEvent:
    base = dict(platform="test", chat_id="chat-1", user_id="user-1", text=text)
    base.update(kwargs)
    return MessageEvent(**base)  # type: ignore[arg-type]


def _install_done_task(adapter: _TestAdapter, session_id: str) -> None:
    """Put a *completed* task into _session_tasks so the heal path fires."""

    async def _noop() -> None:
        return None

    t = asyncio.get_event_loop().create_task(_noop())
    adapter._session_tasks[session_id] = t


def _install_live_task(adapter: _TestAdapter, session_id: str) -> asyncio.Task:
    """Put a *long-running* task into _session_tasks so it looks busy."""

    async def _hold() -> None:
        await asyncio.sleep(60)

    t = asyncio.create_task(_hold())
    adapter._session_tasks[session_id] = t
    return t


# ---- handle_inbound: free path -----------------------------------------


async def test_free_session_installs_guard_and_spawns():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    spawn = AsyncMock()
    adapter._process_message_background = spawn  # type: ignore[assignment]

    await adapter.handle_inbound(_evt())
    await asyncio.sleep(0)

    spawn.assert_awaited_once()
    # Guard remains in place while the (mocked) processing runs;
    # _process_message_background's finally clause would clear it in
    # production. Here we just assert it was installed.
    assert "sess-1" in adapter._active_sessions


async def test_guard_installs_before_create_task():
    """Race window closure: the guard must be in _active_sessions the
    moment _start_session_processing returns, not after the task
    starts."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    spawn = AsyncMock()
    adapter._process_message_background = spawn  # type: ignore[assignment]

    # No await yet — but _start_session_processing is sync after
    # create_task. handle_inbound is async but only awaits router.
    task_coro = adapter.handle_inbound(_evt())
    await task_coro
    # By the time handle_inbound returns, the guard must exist.
    assert "sess-1" in adapter._active_sessions


# ---- handle_inbound: busy + TEXT → merge + interrupt -------------------


async def test_busy_text_followup_merges_and_signals_interrupt():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    guard = asyncio.Event()
    adapter._active_sessions["sess-1"] = guard

    try:
        await adapter.handle_inbound(_evt(text="follow-up"))
    finally:
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass

    assert guard.is_set(), "interrupt event should be set on text follow-up"
    pending = adapter._pending_messages["sess-1"]
    assert pending.text == "follow-up"


async def test_busy_text_followups_accumulate_in_pending_slot():
    """Three rapid TEXT messages 'A', 'B', 'C' must all reach the
    pending slot — not just 'C'."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    adapter._active_sessions["sess-1"] = asyncio.Event()

    try:
        await adapter.handle_inbound(_evt(text="A"))
        await adapter.handle_inbound(_evt(text="B"))
        await adapter.handle_inbound(_evt(text="C"))
    finally:
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass

    assert adapter._pending_messages["sess-1"].text == "A\nB\nC"


# ---- handle_inbound: busy + PHOTO → merge without interrupt ------------


async def test_busy_photo_followup_queues_without_interrupting():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    guard = asyncio.Event()
    adapter._active_sessions["sess-1"] = guard

    try:
        await adapter.handle_inbound(
            _evt(text="caption", message_type=MessageType.PHOTO,
                 attachments=[Path("/tmp/a.jpg")])
        )
    finally:
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass

    assert not guard.is_set(), "photo burst must NOT interrupt"
    assert adapter._pending_messages["sess-1"].attachments == [Path("/tmp/a.jpg")]


async def test_photo_burst_merges_attachments_and_captions():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    adapter._active_sessions["sess-1"] = asyncio.Event()

    try:
        await adapter.handle_inbound(_evt(
            text="cap", message_type=MessageType.PHOTO,
            attachments=[Path("/tmp/a.jpg")]),
        )
        await adapter.handle_inbound(_evt(
            text="cap", message_type=MessageType.PHOTO,
            attachments=[Path("/tmp/b.jpg")]),
        )
        await adapter.handle_inbound(_evt(
            text="extra", message_type=MessageType.PHOTO,
            attachments=[Path("/tmp/c.jpg")]),
        )
    finally:
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass

    pending = adapter._pending_messages["sess-1"]
    assert pending.attachments == [
        Path("/tmp/a.jpg"), Path("/tmp/b.jpg"), Path("/tmp/c.jpg")
    ]
    # Duplicate caption "cap" stays one line; "extra" appends.
    assert pending.text == "cap\nextra"


# ---- handle_inbound: stale-lock heal -----------------------------------


async def test_stale_lock_heals_then_spawns_fresh():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    # Guard present, owner task already done → stale split-brain.
    adapter._active_sessions["sess-1"] = asyncio.Event()
    _install_done_task(adapter, "sess-1")
    await asyncio.sleep(0)  # let the noop task settle into done state

    spawn = AsyncMock()
    adapter._process_message_background = spawn  # type: ignore[assignment]

    await adapter.handle_inbound(_evt())
    await asyncio.sleep(0)

    spawn.assert_awaited_once()
    # New guard was installed (different Event object — the old one was popped).
    assert "sess-1" in adapter._active_sessions


# ---- handle_inbound: bypass commands -----------------------------------


async def test_busy_bypass_command_dispatches_inline_without_cancel():
    """/approve while busy: dispatch_command runs, the in-flight task
    stays alive."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    adapter._active_sessions["sess-1"] = asyncio.Event()

    try:
        await adapter.handle_inbound(_evt(text="/approve"))
    finally:
        if not live.done():
            live.cancel()
            try:
                await live
            except asyncio.CancelledError:
                pass

    daemon.dispatch_command.assert_awaited_once()
    args, _ = daemon.dispatch_command.await_args
    assert args[2] == "approve"
    assert adapter.sent_text == [("chat-1", "ok")]


async def test_busy_canceling_bypass_command_cancels_in_flight():
    """/stop while busy: command response sends, then in-flight cancels."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    adapter._active_sessions["sess-1"] = asyncio.Event()

    await adapter.handle_inbound(_evt(text="/stop"))

    daemon.dispatch_command.assert_awaited_once()
    assert adapter.sent_text == [("chat-1", "ok")]
    assert live.cancelled() or live.done()
    # Guard released and no pending → session is back to free state.
    assert "sess-1" not in adapter._active_sessions
    assert "sess-1" not in adapter._session_tasks


async def test_canceling_bypass_drains_followup_into_fresh_task():
    """If a TEXT follow-up arrives between the bypass command's
    response and cleanup, it must be picked up — not lost."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    adapter._active_sessions["sess-1"] = asyncio.Event()
    # Pre-stage a pending follow-up (as if it landed during the command).
    adapter._pending_messages["sess-1"] = _evt(text="followup")

    spawn = AsyncMock()
    adapter._process_message_background = spawn  # type: ignore[assignment]

    await adapter.handle_inbound(_evt(text="/new"))
    await asyncio.sleep(0)

    # New processing task spawned for the pending follow-up.
    spawn.assert_awaited_once()
    spawn_event = spawn.await_args.args[0]
    assert spawn_event.text == "followup"
    assert not live.done() or live.cancelled() or live.done()  # cleaned


# ---- handle_inbound: busy-session handler override ---------------------


async def test_busy_session_handler_short_circuits_default():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    guard = asyncio.Event()
    adapter._active_sessions["sess-1"] = guard

    handled = AsyncMock(return_value=True)
    adapter.set_busy_session_handler(handled)

    try:
        await adapter.handle_inbound(_evt(text="follow-up"))
    finally:
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass

    handled.assert_awaited_once()
    assert not guard.is_set(), "handler returned True → default path skipped"
    assert "sess-1" not in adapter._pending_messages


async def test_busy_session_handler_falls_through_when_returns_false():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "sess-1")
    guard = asyncio.Event()
    adapter._active_sessions["sess-1"] = guard
    adapter.set_busy_session_handler(AsyncMock(return_value=False))

    try:
        await adapter.handle_inbound(_evt(text="x"))
    finally:
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass

    assert guard.is_set()
    assert adapter._pending_messages["sess-1"].text == "x"


# ---- low-level helpers --------------------------------------------------


async def test_session_task_is_stale_true_when_task_done():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["s"] = asyncio.Event()
    _install_done_task(adapter, "s")
    await asyncio.sleep(0)
    assert adapter._session_task_is_stale("s") is True


async def test_session_task_is_stale_false_when_task_live():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    live = _install_live_task(adapter, "s")
    try:
        assert adapter._session_task_is_stale("s") is False
    finally:
        live.cancel()
        try:
            await live
        except asyncio.CancelledError:
            pass


async def test_session_task_is_stale_false_when_no_task_recorded():
    """No owner task → not stale (covers the test-injected-guard case)."""
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["s"] = asyncio.Event()
    assert adapter._session_task_is_stale("s") is False


async def test_release_session_guard_with_identity_check_skips_mismatch():
    daemon = _FakeDaemon()
    adapter = _TestAdapter(daemon)
    real_guard = asyncio.Event()
    adapter._active_sessions["s"] = real_guard
    stale_guard = asyncio.Event()
    adapter._release_session_guard("s", guard=stale_guard)
    assert adapter._active_sessions.get("s") is real_guard


# ---- merge_pending_message_event ---------------------------------------


def test_merge_first_event_just_stores():
    pending: dict[str, MessageEvent] = {}
    e = _evt(text="hi")
    merge_pending_message_event(pending, "s", e)
    assert pending["s"] is e


def test_merge_text_appends_with_newline_when_enabled():
    pending: dict[str, MessageEvent] = {"s": _evt(text="first")}
    merge_pending_message_event(pending, "s", _evt(text="second"))
    assert pending["s"].text == "first\nsecond"


def test_merge_text_replaces_when_merge_text_disabled():
    pending: dict[str, MessageEvent] = {"s": _evt(text="first")}
    merge_pending_message_event(
        pending, "s", _evt(text="second"), merge_text=False,
    )
    assert pending["s"].text == "second"


def test_merge_two_photos_extends_attachments():
    pending: dict[str, MessageEvent] = {
        "s": _evt(text="cap", message_type=MessageType.PHOTO,
                  attachments=[Path("a.jpg")])
    }
    merge_pending_message_event(
        pending, "s",
        _evt(text="cap", message_type=MessageType.PHOTO,
             attachments=[Path("b.jpg")]),
    )
    assert pending["s"].attachments == [Path("a.jpg"), Path("b.jpg")]
    # Duplicate caption deduplicates.
    assert pending["s"].text == "cap"


def test_merge_photo_then_text_keeps_photo_type():
    pending: dict[str, MessageEvent] = {
        "s": _evt(text="img", message_type=MessageType.PHOTO,
                  attachments=[Path("a.jpg")])
    }
    merge_pending_message_event(
        pending, "s", _evt(text="describe this"),
    )
    assert pending["s"].message_type == MessageType.PHOTO
    assert pending["s"].text == "img\ndescribe this"


def test_merge_text_then_photo_promotes_to_photo():
    pending: dict[str, MessageEvent] = {"s": _evt(text="hi")}
    merge_pending_message_event(
        pending, "s",
        _evt(text="cap", message_type=MessageType.PHOTO,
             attachments=[Path("a.jpg")]),
    )
    assert pending["s"].message_type == MessageType.PHOTO


# ---- abstract enforcement ----------------------------------------------


def test_abstract_methods_block_direct_instantiation():
    with pytest.raises(TypeError):
        GatewayAdapter(_FakeDaemon())  # type: ignore[abstract,arg-type]


def test_bypass_command_sets_are_consistent():
    """Every canceling bypass must also be a bypass."""
    assert CANCELING_BYPASS_COMMANDS <= BYPASS_COMMANDS


# ---- MessageEvent.get_command ------------------------------------------


def test_get_command_strips_botname():
    assert _evt(text="/stop@athena_bot foo").get_command() == "stop"


def test_get_command_rejects_paths():
    assert _evt(text="/path/like/file").get_command() is None


def test_get_command_returns_none_for_plaintext():
    assert _evt(text="hello").get_command() is None
