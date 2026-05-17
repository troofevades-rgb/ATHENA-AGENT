"""End-to-end stress test: many concurrent sessions through one daemon.

Goal: drive the gateway daemon hard enough to surface deadlocks,
races, or pool-leak bugs that wouldn't show up in unit tests.
Specifically:

- 100 concurrent sessions, each receiving a burst of inbound events,
  exercise the router's lock + agent pool's instantiation locks +
  per-adapter session guards simultaneously.
- A subset of events arrive while their session is busy, triggering
  the pending-merge / interrupt path.
- The full set must complete in bounded time (no deadlock) and the
  pool must end in a sane state (size capped, all sessions
  evicted on shutdown).

The agent is a deterministic stub — we're not measuring LLM
throughput here, only the gateway's plumbing.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from athena.config import Config, GatewayConfig
from athena.gateway.base import GatewayAdapter
from athena.gateway.daemon import GatewayDaemon
from athena.gateway.events import MessageEvent
from athena.gateway import registry as gw_registry


# ---- doubles ---------------------------------------------------------


class _StubAgent:
    """Minimal sync agent surface — records the prompt, returns a
    deterministic response. No I/O."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.run_count = 0
        self.last_prompt: str | None = None

    def run_until_done(self, text: str = "", *, max_iterations: int | None = None) -> None:
        self.run_count += 1
        self.last_prompt = text

    def last_assistant_message(self) -> str:
        return f"echo:{self.last_prompt or ''}"

    async def close(self) -> None:
        pass


class _RecordingAdapter(GatewayAdapter):
    """Concrete adapter that records every send and never touches a
    network. Subclass to give it a name."""

    name = "stub"
    body_cap = 10_000  # avoid chunking in stress test

    def __init__(self, daemon: GatewayDaemon) -> None:
        super().__init__(daemon)
        self.sent_text: list[tuple[str, str]] = []
        self.send_lock = asyncio.Lock()

    async def start(self) -> None:
        # Park forever; the daemon's start kicks this in a task and
        # cancels it via stop().
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        pass

    async def send_text(self, chat_id: str, text: str) -> str:
        async with self.send_lock:
            self.sent_text.append((chat_id, text))
        return "msg-id"

    async def send_file(
        self, chat_id: str, file_path: Path, caption: str | None = None,
    ) -> str:
        return "msg-id"

    async def show_typing(self, chat_id: str) -> None:
        return None


# ---- fixtures --------------------------------------------------------


@pytest.fixture
def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GatewayDaemon:
    """A daemon with: stub agent factory, the recording adapter,
    isolated profile dir, no real provider."""
    from athena import config as cfg_mod
    from athena.gateway import daemon as daemon_mod

    def fake_profile_dir(name: str = "default", home: Path | None = None) -> Path:
        return tmp_path / "profiles" / name

    monkeypatch.setattr(cfg_mod, "profile_dir", fake_profile_dir)
    monkeypatch.setattr(daemon_mod, "profile_dir", fake_profile_dir)

    cfg = Config(profile="stress")
    cfg.gateway = GatewayConfig(max_warm_agents=20)  # smaller than session count

    async def stub_factory(session_id: str) -> _StubAgent:
        return _StubAgent(session_id)

    d = GatewayDaemon(cfg, agent_factory=stub_factory)
    yield d

    gw_registry._clear_for_tests()


# ---- tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_100_concurrent_sessions_complete_without_deadlock(
    daemon: GatewayDaemon,
) -> None:
    """Fire one inbound per (platform, chat, user) for 100 distinct
    chats concurrently. Every one should produce a response and the
    daemon should shut down cleanly within bounded time."""
    adapter = _RecordingAdapter(daemon)
    daemon.register(adapter)
    await daemon.start()

    n_sessions = 100
    inbound = [
        MessageEvent(
            platform="stub",
            chat_id=f"chat-{i:03d}",
            user_id=f"user-{i:03d}",
            text=f"hello-{i}",
        )
        for i in range(n_sessions)
    ]

    start = time.monotonic()
    try:
        await asyncio.gather(*(adapter.handle_inbound(e) for e in inbound))
        # Give spawned _process tasks time to drain.
        deadline = start + 30.0
        while (
            len(adapter.sent_text) < n_sessions
            and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.05)
    finally:
        await daemon.stop()

    elapsed = time.monotonic() - start
    assert len(adapter.sent_text) == n_sessions, (
        f"only {len(adapter.sent_text)} of {n_sessions} responses delivered "
        f"in {elapsed:.2f}s (deadlock or leak?)"
    )
    assert elapsed < 30.0, f"100-session run took {elapsed:.2f}s (likely contention)"
    # No leaked sessions: pool drained on stop.
    assert daemon.pool.size == 0


@pytest.mark.asyncio
async def test_burst_to_same_session_merges_into_pending(
    daemon: GatewayDaemon,
) -> None:
    """Three rapid messages on the same chat: the agent runs once for
    the first, the other two merge into pending and run as a single
    follow-up turn."""
    adapter = _RecordingAdapter(daemon)
    daemon.register(adapter)
    await daemon.start()

    chat_id, user_id = "chat-burst", "user-burst"
    events = [
        MessageEvent(platform="stub", chat_id=chat_id, user_id=user_id, text="A"),
        MessageEvent(platform="stub", chat_id=chat_id, user_id=user_id, text="B"),
        MessageEvent(platform="stub", chat_id=chat_id, user_id=user_id, text="C"),
    ]

    try:
        # Fire them with minimal gaps so B and C arrive while A is processing.
        await adapter.handle_inbound(events[0])
        await adapter.handle_inbound(events[1])
        await adapter.handle_inbound(events[2])
        # Wait for pending drain.
        deadline = time.monotonic() + 5.0
        while (
            len(adapter.sent_text) < 2
            and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.01)
    finally:
        await daemon.stop()

    # First turn echoes "A". Pending merge gives the second turn
    # "B\nC" (or "B\nC" prefixed with "_busy" ack — but the busy ack
    # only fires on the new policy when busy_session_handler is set;
    # we don't set one). The base merges text follow-ups into a
    # single pending event.
    bodies = [t for _, t in adapter.sent_text]
    assert "echo:A" in bodies
    assert any("B" in b and "C" in b for b in bodies)


@pytest.mark.asyncio
async def test_daemon_stop_drains_pool_completely(
    daemon: GatewayDaemon,
) -> None:
    """After stop(), the pool must be empty so no warm agent leaks
    across daemon restarts."""
    adapter = _RecordingAdapter(daemon)
    daemon.register(adapter)
    await daemon.start()

    for i in range(5):
        await adapter.handle_inbound(MessageEvent(
            platform="stub", chat_id=f"c{i}", user_id=f"u{i}", text=f"hi {i}",
        ))
        await asyncio.sleep(0.01)
    # Let turns finish.
    await asyncio.sleep(0.5)

    assert daemon.pool.size > 0
    await daemon.stop()
    assert daemon.pool.size == 0
