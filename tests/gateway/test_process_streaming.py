"""GatewayAdapter._process_message_background — end-to-end gateway
turn handling.

Tests the full lifecycle:
- agent pool resolution, history replay (mocked agent)
- approval callback bridge installation
- run_until_done on a worker thread
- final response chunked and sent back
- typing heartbeat task spawned and cancelled
- pending follow-up drained into a fresh task
- error paths (pool failure, agent crash, send failure)
- text chunking edge cases
- user-text builder including attachments
- agent resume from JSONL
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from athena.gateway import registry as gw_registry
from athena.gateway.base import (
    GatewayAdapter,
    _build_user_text,
    _chunk_text,
)
from athena.gateway.events import MessageEvent, MessageType

# ---- doubles ---------------------------------------------------------


class _FakeRouter:
    def __init__(self, *, session_id: str = "sess-1") -> None:
        self.session_id = session_id

    async def resolve(self, event):
        return self.session_id

    def list_routes(self, *, platform=None):
        return []


class _FakeApprovals:
    def __init__(self) -> None:
        self._loop = None
        self.requests: list[tuple[str, str, dict]] = []

    def bind_loop(self, loop):
        self._loop = loop

    def cancel_all(self):
        pass

    def register_platform_renderer(self, platform, renderer):
        pass

    def request_sync(
        self,
        *,
        session_id,
        tool_name,
        tool_args,
        platform,
        chat_id,
        timeout=None,
    ):
        self.requests.append((session_id, tool_name, dict(tool_args)))
        return "deny"


class _FakePool:
    def __init__(self) -> None:
        self.agents: dict[str, Any] = {}
        self.get_calls: list[str] = []
        self.fail_get = False

    @contextlib.asynccontextmanager
    async def use(self, session_id: str):
        """Mirrors the real AgentPool.use contract — yield the agent
        and let the gateway dispatch run inside the context."""
        agent = await self.get(session_id)
        try:
            yield agent
        finally:
            pass

    async def get(self, session_id: str):
        self.get_calls.append(session_id)
        if self.fail_get:
            raise RuntimeError("pool unavailable")
        agent = self.agents.get(session_id)
        if agent is None:
            agent = SimpleNamespace(
                session_id=session_id,
                run_until_done=lambda text="": setattr(
                    agent,
                    "last_text",
                    text,
                ),
                last_assistant_message=lambda: f"response-to-{getattr(agent, 'last_text', '')}",
            )
            self.agents[session_id] = agent
        return agent

    async def evict_all(self) -> None:
        self.agents.clear()


class _FakeDaemon:
    def __init__(self, tmp_path: Path) -> None:
        self.router = _FakeRouter()
        self.approvals = _FakeApprovals()
        self.pool = _FakePool()
        self.profile_dir = tmp_path / "profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = SimpleNamespace(profile="default", model="m")
        self.adapters = []


class _TestAdapter(GatewayAdapter):
    name = "test"
    body_cap = 100  # so chunking is testable with short strings

    def __init__(self, daemon: _FakeDaemon) -> None:
        super().__init__(daemon)  # type: ignore[arg-type]
        self.sent_text: list[tuple[str, str]] = []
        self.sent_files: list[tuple[str, Path, str | None]] = []
        self.typing_calls: list[str] = []
        self.send_text_should_raise = False

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_text(self, chat_id: str, text: str) -> str:
        if self.send_text_should_raise:
            raise RuntimeError("network down")
        self.sent_text.append((chat_id, text))
        return "msg-id"

    async def send_file(self, chat_id: str, file_path: Path, caption: str | None = None) -> str:
        self.sent_files.append((chat_id, file_path, caption))
        return "msg-id"

    async def show_typing(self, chat_id: str) -> None:
        self.typing_calls.append(chat_id)


def _evt(text: str = "hi", chat_id: str = "chat-1", **kwargs) -> MessageEvent:
    base = dict(platform="test", chat_id=chat_id, user_id="user-1", text=text)
    base.update(kwargs)
    return MessageEvent(**base)


# ---- happy path -------------------------------------------------------


async def test_process_sends_final_response_back(tmp_path: Path) -> None:
    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    # Pre-install the guard as handle_inbound would have.
    guard = asyncio.Event()
    adapter._active_sessions["sess-1"] = guard

    await adapter._process_message_background(_evt(text="hello"), "sess-1")

    assert daemon.pool.get_calls == ["sess-1"]
    assert adapter.sent_text == [("chat-1", "response-to-hello")]
    # Guard released after processing so the session is ready again.
    assert "sess-1" not in adapter._active_sessions


async def test_process_releases_guard_in_finally(tmp_path: Path) -> None:
    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    guard = asyncio.Event()
    adapter._active_sessions["sess-1"] = guard
    adapter._session_tasks["sess-1"] = MagicMock()

    # Force agent.run_until_done to raise.
    daemon.pool.agents["sess-1"] = SimpleNamespace(
        run_until_done=MagicMock(side_effect=RuntimeError("boom")),
        last_assistant_message=lambda: "",
    )

    await adapter._process_message_background(_evt(), "sess-1")

    # Even after the agent crashed, the guard and session_tasks slot
    # released so the chat isn't wedged.
    assert "sess-1" not in adapter._active_sessions
    assert "sess-1" not in adapter._session_tasks
    # User got the error message.
    assert any("processing failed" in t for _, t in adapter.sent_text)


# ---- approval bridge --------------------------------------------------


async def test_approval_callback_installed_on_worker_thread(
    tmp_path: Path,
) -> None:
    """The agent's approval_callback during run_until_done must be
    the gateway bridge — not the default terminal prompt."""
    from athena.safety.approval_callback import get_approval_callback

    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["sess-1"] = asyncio.Event()

    captured: list[Any] = []

    def fake_run(text=""):
        # While the agent is "running", the callback should be the
        # gateway bridge. Trigger it to confirm.
        cb = get_approval_callback()
        result = cb("Bash", {"cmd": "rm -rf /"})
        captured.append(("decision", result))
        captured.append(("callback", cb))

    daemon.pool.agents["sess-1"] = SimpleNamespace(
        run_until_done=fake_run,
        last_assistant_message=lambda: "done",
    )

    await adapter._process_message_background(_evt(), "sess-1")

    # The callback that fired was the gateway bridge (we hooked it
    # via _FakeApprovals.request_sync, which records the request).
    assert captured[0] == ("decision", "deny")
    assert daemon.approvals.requests == [
        ("sess-1", "Bash", {"cmd": "rm -rf /"}),
    ]


async def test_approval_callback_reset_after_run(tmp_path: Path) -> None:
    """ContextVar token must be reset so a subsequent foreground call
    in the same context sees the default callback again."""
    from athena.safety.approval_callback import (
        _interactive_approval,
        get_approval_callback,
    )

    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["sess-1"] = asyncio.Event()

    await adapter._process_message_background(_evt(), "sess-1")

    assert get_approval_callback() is _interactive_approval


# ---- typing heartbeat -------------------------------------------------


async def test_typing_heartbeat_fires_during_long_run(tmp_path: Path) -> None:
    """The typing-indicator task fires periodically while
    run_until_done is awaited via asyncio.to_thread."""
    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["sess-1"] = asyncio.Event()

    # Shorten the heartbeat cadence so the test doesn't take 4s.
    import athena.gateway.base as base_mod

    monkey_orig = base_mod._TYPING_REFRESH_SECONDS
    base_mod._TYPING_REFRESH_SECONDS = 0.01

    try:
        # Simulate a 50ms agent run so the heartbeat fires a few times.
        def slow_run(text=""):
            import time

            time.sleep(0.05)

        daemon.pool.agents["sess-1"] = SimpleNamespace(
            run_until_done=slow_run,
            last_assistant_message=lambda: "done",
        )
        await adapter._process_message_background(_evt(), "sess-1")
    finally:
        base_mod._TYPING_REFRESH_SECONDS = monkey_orig

    # At least one typing call should have fired during the run.
    assert len(adapter.typing_calls) >= 1
    assert all(c == "chat-1" for c in adapter.typing_calls)


async def test_typing_heartbeat_cancelled_on_exit(tmp_path: Path) -> None:
    """The heartbeat task must NOT keep firing after the run
    completes (would leak forever)."""
    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["sess-1"] = asyncio.Event()

    import athena.gateway.base as base_mod

    monkey_orig = base_mod._TYPING_REFRESH_SECONDS
    base_mod._TYPING_REFRESH_SECONDS = 0.005

    try:
        await adapter._process_message_background(_evt(), "sess-1")
        # Wait longer than the cadence to confirm no more typing fires.
        baseline = len(adapter.typing_calls)
        await asyncio.sleep(0.02)
        assert len(adapter.typing_calls) == baseline
    finally:
        base_mod._TYPING_REFRESH_SECONDS = monkey_orig


# ---- pool failure path -----------------------------------------------


async def test_pool_failure_sends_error_message(tmp_path: Path) -> None:
    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["sess-1"] = asyncio.Event()
    daemon.pool.fail_get = True

    await adapter._process_message_background(_evt(), "sess-1")

    assert any("failed to load session" in t for _, t in adapter.sent_text)
    assert "sess-1" not in adapter._active_sessions


# ---- pending drain ---------------------------------------------------


async def test_pending_drain_spawns_fresh_task(tmp_path: Path) -> None:
    """If a follow-up message lands while the agent is running, it
    must be picked up after the run completes — not sit waiting for
    another message."""
    daemon = _FakeDaemon(tmp_path)
    daemon.approvals.bind_loop(asyncio.get_running_loop())
    adapter = _TestAdapter(daemon)
    adapter._active_sessions["sess-1"] = asyncio.Event()
    adapter._pending_messages["sess-1"] = _evt(text="follow-up")

    # First run sends one response, then pending is drained which
    # spawns a new task that sends another response.
    await adapter._process_message_background(_evt(text="initial"), "sess-1")
    # Let the spawned task run.
    await asyncio.sleep(0.1)

    # Two sends: one for the initial turn, one for the drained pending turn.
    bodies = [t for _, t in adapter.sent_text]
    assert "response-to-initial" in bodies
    assert "response-to-follow-up" in bodies


# ---- chunking --------------------------------------------------------


def test_chunk_text_short_passes_through() -> None:
    assert _chunk_text("hi", cap=100) == ["hi"]


def test_chunk_text_empty_string_returns_empty_list() -> None:
    assert _chunk_text("", cap=100) == []


def test_chunk_text_splits_on_paragraph_boundary() -> None:
    text = "first paragraph.\n\nsecond paragraph that is longer than the cap."
    chunks = _chunk_text(text, cap=30)
    assert len(chunks) >= 2
    # The first chunk ends at the paragraph break (not mid-sentence).
    assert chunks[0] == "first paragraph."


def test_chunk_text_splits_on_sentence_boundary_when_no_paragraph() -> None:
    text = "Sentence one. Sentence two. Sentence three is at the end."
    chunks = _chunk_text(text, cap=30)
    # First chunk ends on ". " boundary.
    assert chunks[0].endswith(".")


def test_chunk_text_hard_cuts_when_no_boundary() -> None:
    text = "x" * 250
    chunks = _chunk_text(text, cap=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == text


def test_chunk_text_does_not_produce_tiny_chunks() -> None:
    """A boundary at 10% of cap shouldn't trigger a split — we'd
    rather emit one big chunk than a 10-char + 90-char pair."""
    text = "X. " + "y" * 297
    chunks = _chunk_text(text, cap=100)
    # Should not split right after the "X." (would produce a 2-char chunk).
    assert all(len(c) >= 30 for c in chunks if c is not chunks[-1])


async def test_send_chunked_sends_each_chunk(tmp_path: Path) -> None:
    daemon = _FakeDaemon(tmp_path)
    adapter = _TestAdapter(daemon)
    text = "x" * 250  # > cap=100 → 3 chunks
    await adapter._send_chunked("chat-1", text)
    assert len(adapter.sent_text) == 3
    assert "".join(t for _, t in adapter.sent_text) == text


async def test_send_chunked_stops_on_send_failure(tmp_path: Path) -> None:
    daemon = _FakeDaemon(tmp_path)
    adapter = _TestAdapter(daemon)
    adapter.send_text_should_raise = True
    await adapter._send_chunked("chat-1", "x" * 250)
    # Failed sends don't crash — they log + bail.


# ---- user-text builder -----------------------------------------------


def test_build_user_text_passthrough_for_plain_text() -> None:
    assert _build_user_text(_evt(text="hello")) == "hello"


def test_build_user_text_appends_attachment_paths(tmp_path: Path) -> None:
    event = _evt(
        text="check this out",
        message_type=MessageType.PHOTO,
        attachments=[tmp_path / "a.jpg", tmp_path / "b.png"],
    )
    text = _build_user_text(event)
    assert "check this out" in text
    assert "a.jpg" in text
    assert "b.png" in text
    assert "attached files" in text


def test_build_user_text_attachments_only_no_caption(tmp_path: Path) -> None:
    event = _evt(
        text="",
        message_type=MessageType.PHOTO,
        attachments=[tmp_path / "x.jpg"],
    )
    text = _build_user_text(event)
    assert "x.jpg" in text


# ---- agent factory ---------------------------------------------------


async def test_agent_factory_resumes_from_jsonl(tmp_path: Path) -> None:
    """The factory must load conversation history from the session's
    JSONL into the agent's messages list."""
    import json as _json

    from athena.config import Config
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="agentfactory-test", model="qwen2.5-coder:14b")
    # Build a daemon (with a stubbed approvals/pool so we just get the
    # factory wired in).
    monkey = pytest.MonkeyPatch()
    try:
        from athena import config as cfg_mod
        from athena.gateway import daemon as daemon_mod

        def fake_profile_dir(name="default", home=None):
            return tmp_path / "home" / name

        monkey.setattr(cfg_mod, "profile_dir", fake_profile_dir)
        monkey.setattr(daemon_mod, "profile_dir", fake_profile_dir)

        daemon = GatewayDaemon(cfg)

        # Pre-populate a JSONL for session "resume-me".
        sessions_dir = daemon.session_store.sessions_dir
        sessions_dir.mkdir(parents=True, exist_ok=True)
        jsonl = sessions_dir / "resume-me.jsonl"
        jsonl.write_text(
            _json.dumps({"role": "user", "content": "prior question"})
            + "\n"
            + _json.dumps({"role": "assistant", "content": "prior answer"})
            + "\n",
            encoding="utf-8",
        )

        # Mock out the Provider construction so we don't need ollama.
        from athena.providers import _REGISTRY
        from athena.providers.base import Provider, StreamChunk

        class _FakeProvider(Provider):
            name = "ollama"
            requires_api_key = False

            def __init__(self, *a, **kw):
                pass

            def show_model(self, model):
                return {"system": ""}

            def list_models(self):
                return []

            def stream_chat(self, **kw):
                yield StreamChunk("end", {"reason": "stop"})

            def parse_tool_calls(self, content, raw_response):
                return content, []

            def close(self):
                pass

        saved = _REGISTRY.get("ollama")
        _REGISTRY["ollama"] = _FakeProvider
        try:
            agent = await daemon.pool.get("resume-me")
        finally:
            if saved:
                _REGISTRY["ollama"] = saved
            else:
                _REGISTRY.pop("ollama", None)

        assert agent.session_id == "resume-me"
        # Messages should include the system + 2 replayed turns.
        replayed = [m for m in agent.messages if m.get("role") != "system"]
        assert len(replayed) == 2
        assert replayed[0]["content"] == "prior question"
        assert replayed[1]["content"] == "prior answer"
    finally:
        monkey.undo()
        gw_registry._clear_for_tests()
