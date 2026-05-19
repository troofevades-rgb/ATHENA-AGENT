"""SlackAdapter — slack-sdk Socket Mode wrapper.

slack-sdk's SocketModeClient + AsyncWebClient are heavily networked;
mock them. The adapter's normalize / route / render surface is
testable in isolation.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx

from athena.gateway.events import ApprovalRequest, MessageEvent, MessageType
from athena.gateway.platforms.slack import (
    _ACTION_PREFIX,
    SlackAdapter,
)


class _FakeRouter:
    def __init__(self, *, session_id: str = "sess-1") -> None:
        self.session_id = session_id
        self.calls: list[MessageEvent] = []
        self.routes: list = []

    async def resolve(self, event):
        self.calls.append(event)
        return self.session_id

    def list_routes(self, *, platform=None):
        return list(self.routes)


class _FakeApprovals:
    def __init__(self) -> None:
        self.renderers: dict[str, object] = {}
        self.resolves: list[tuple[str, str]] = []

    def register_platform_renderer(self, platform, renderer):
        if renderer is None:
            self.renderers.pop(platform, None)
        else:
            self.renderers[platform] = renderer

    def resolve(self, request_id: str, decision: str) -> bool:
        self.resolves.append((request_id, decision))
        return True


class _FakeDaemon:
    def __init__(self, tmp_path: Path) -> None:
        self.router = _FakeRouter()
        self.approvals = _FakeApprovals()
        self.profile_dir = tmp_path / "profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)


def _adapter(tmp_path: Path) -> SlackAdapter:
    return SlackAdapter(
        _FakeDaemon(tmp_path),
        bot_token="xoxb-test",
        app_token="xapp-test",
    )


# ---- constructor ------------------------------------------------------


def test_construct_validates_bot_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SlackAdapter(_FakeDaemon(tmp_path), bot_token="", app_token="xapp-x")
    with pytest.raises(ValueError):
        SlackAdapter(_FakeDaemon(tmp_path), bot_token="oxen", app_token="xapp-x")


def test_construct_validates_app_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SlackAdapter(_FakeDaemon(tmp_path), bot_token="xoxb-x", app_token="")
    with pytest.raises(ValueError):
        SlackAdapter(_FakeDaemon(tmp_path), bot_token="xoxb-x", app_token="ya")


def test_name_is_slack(tmp_path: Path) -> None:
    assert _adapter(tmp_path).name == "slack"


# ---- event normalization ---------------------------------------------


async def test_text_message_event_normalized(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_slack(
        {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "channel_type": "im",
            "ts": "1700000000.000",
            "text": "hello there",
        }
    )
    assert event.platform == "slack"
    assert event.user_id == "U1"
    assert event.chat_id == "C1"
    assert event.text == "hello there"
    assert event.message_type == MessageType.TEXT
    assert event.is_dm is True
    assert event.platform_message_id == "1700000000.000"


async def test_channel_message_marked_not_dm(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_slack(
        {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "channel_type": "channel",
            "ts": "1.0",
            "text": "hi",
        }
    )
    assert event.is_dm is False


async def test_thread_ts_becomes_reply_to(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_slack(
        {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "channel_type": "channel",
            "ts": "2.0",
            "thread_ts": "1.0",
            "text": "reply",
        }
    )
    assert event.reply_to_message_id == "1.0"


async def test_thread_root_does_not_self_reply(tmp_path: Path) -> None:
    """If ts == thread_ts, this IS the thread root — don't claim to
    be replying to itself."""
    a = _adapter(tmp_path)
    event = await a._event_from_slack(
        {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "ts": "1.0",
            "thread_ts": "1.0",
            "text": "root",
        }
    )
    assert event.reply_to_message_id is None


async def test_image_file_classifies_as_photo(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()  # any non-None — actual download mocked below
    async with respx.mock(base_url="https://files.slack.com") as mock:
        mock.get("/dl/abc.jpg").mock(
            return_value=__import__("httpx").Response(200, content=b"FAKE")
        )
        event = await a._event_from_slack(
            {
                "type": "message",
                "user": "U",
                "channel": "C",
                "ts": "1.0",
                "text": "look",
                "files": [
                    {
                        "id": "F1",
                        "name": "abc.jpg",
                        "mimetype": "image/jpeg",
                        "url_private_download": "https://files.slack.com/dl/abc.jpg",
                    }
                ],
            }
        )
    assert event.message_type == MessageType.PHOTO
    assert len(event.attachments) == 1
    assert event.attachments[0].name == "abc.jpg"
    assert event.attachments[0].read_bytes() == b"FAKE"


async def test_audio_file_classifies_as_audio(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()
    async with respx.mock(base_url="https://files.slack.com") as mock:
        mock.get("/dl/v.mp3").mock(return_value=__import__("httpx").Response(200, content=b"AUD"))
        event = await a._event_from_slack(
            {
                "type": "message",
                "user": "U",
                "channel": "C",
                "ts": "1.0",
                "text": "",
                "files": [
                    {
                        "id": "F",
                        "name": "v.mp3",
                        "mimetype": "audio/mpeg",
                        "url_private_download": "https://files.slack.com/dl/v.mp3",
                    }
                ],
            }
        )
    assert event.message_type == MessageType.AUDIO


async def test_unknown_mime_classifies_as_document(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()
    async with respx.mock(base_url="https://files.slack.com") as mock:
        mock.get("/dl/r.pdf").mock(return_value=__import__("httpx").Response(200, content=b"PDF"))
        event = await a._event_from_slack(
            {
                "type": "message",
                "user": "U",
                "channel": "C",
                "ts": "1.0",
                "text": "",
                "files": [
                    {
                        "id": "F",
                        "name": "r.pdf",
                        "mimetype": "application/pdf",
                        "url_private_download": "https://files.slack.com/dl/r.pdf",
                    }
                ],
            }
        )
    assert event.message_type == MessageType.DOCUMENT


async def test_file_download_failure_skips(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()
    async with respx.mock(base_url="https://files.slack.com") as mock:
        mock.get("/dl/x.png").mock(return_value=__import__("httpx").Response(403))
        event = await a._event_from_slack(
            {
                "type": "message",
                "user": "U",
                "channel": "C",
                "ts": "1.0",
                "text": "",
                "files": [
                    {
                        "id": "F",
                        "name": "x.png",
                        "mimetype": "image/png",
                        "url_private_download": "https://files.slack.com/dl/x.png",
                    }
                ],
            }
        )
    # Type still PHOTO (classified from mimetype), but no attachments.
    assert event.message_type == MessageType.PHOTO
    assert event.attachments == []


# ---- _should_skip (bot self-filter) ----------------------------------


def test_skip_bot_id_messages(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert a._should_skip({"bot_id": "B1"}) is True


def test_skip_bot_message_subtype(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert a._should_skip({"subtype": "bot_message"}) is True


def test_skip_our_own_user_id(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._bot_user_id = "U_BOT"
    assert a._should_skip({"user": "U_BOT"}) is True


def test_does_not_skip_normal_user_message(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._bot_user_id = "U_BOT"
    assert a._should_skip({"user": "U_OTHER"}) is False


# ---- _handle_event fan-out --------------------------------------------


async def test_handle_event_routes_to_inbound(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._handle_event(
        {
            "event": {
                "type": "message",
                "user": "U",
                "channel": "C",
                "channel_type": "im",
                "ts": "1.0",
                "text": "hi",
            }
        }
    )
    a.handle_inbound.assert_awaited_once()


async def test_handle_event_ignores_non_message_types(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._handle_event({"event": {"type": "reaction_added"}})
    a.handle_inbound.assert_not_awaited()


async def test_handle_event_ignores_missing_event(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._handle_event({})
    a.handle_inbound.assert_not_awaited()


async def test_handle_event_skips_bot_self(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._handle_event({"event": {"type": "message", "bot_id": "B1", "text": "hi"}})
    a.handle_inbound.assert_not_awaited()


# ---- interactive (block_actions) -------------------------------------


async def test_handle_interactive_routes_allow(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    await a._handle_interactive(
        {
            "type": "block_actions",
            "actions": [
                {"action_id": f"{_ACTION_PREFIX}:r-abc:allow"},
            ],
        }
    )
    assert a.daemon.approvals.resolves == [("r-abc", "allow")]


async def test_handle_interactive_routes_deny(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    await a._handle_interactive(
        {
            "type": "block_actions",
            "actions": [{"action_id": f"{_ACTION_PREFIX}:r-x:deny"}],
        }
    )
    assert a.daemon.approvals.resolves == [("r-x", "deny")]


async def test_handle_interactive_ignores_unrelated_action_ids(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    await a._handle_interactive(
        {
            "type": "block_actions",
            "actions": [{"action_id": "other:thing:here"}],
        }
    )
    assert a.daemon.approvals.resolves == []


async def test_handle_interactive_ignores_non_block_actions(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    await a._handle_interactive(
        {
            "type": "view_submission",
            "actions": [
                {"action_id": f"{_ACTION_PREFIX}:r:allow"},
            ],
        }
    )
    assert a.daemon.approvals.resolves == []


# ---- approval rendering ---------------------------------------------


async def test_render_approval_posts_blocks(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()
    a._web.chat_postMessage = AsyncMock()
    req = ApprovalRequest(
        session_id="s1",
        tool_name="Bash",
        tool_args={"cmd": "ls"},
        request_id="r1",
        platform="slack",
        chat_id="C42",
    )
    await a._render_approval(req)
    a._web.chat_postMessage.assert_awaited_once()
    kwargs = a._web.chat_postMessage.await_args.kwargs
    assert kwargs["channel"] == "C42"
    assert "Bash" in kwargs["text"]
    blocks = kwargs["blocks"]
    assert blocks[0]["type"] == "section"
    assert blocks[1]["type"] == "actions"
    btn_ids = [e["action_id"] for e in blocks[1]["elements"]]
    assert btn_ids == [
        f"{_ACTION_PREFIX}:r1:allow",
        f"{_ACTION_PREFIX}:r1:deny",
    ]


async def test_render_approval_falls_back_to_router_route(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timedelta, timezone

    a = _adapter(tmp_path)
    a._web = MagicMock()
    a._web.chat_postMessage = AsyncMock()
    now = datetime.now(timezone.utc)
    a.daemon.router.routes = [
        SimpleNamespace(
            session_id="s1",
            chat_id="C-OLD",
            platform="slack",
            last_seen_at=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            session_id="s1",
            chat_id="C-NEW",
            platform="slack",
            last_seen_at=now,
        ),
    ]
    req = ApprovalRequest(
        session_id="s1",
        tool_name="Bash",
        tool_args={},
        request_id="r1",
        platform="slack",
    )
    await a._render_approval(req)
    kwargs = a._web.chat_postMessage.await_args.kwargs
    assert kwargs["channel"] == "C-NEW"


async def test_render_approval_drops_when_no_route(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()
    a._web.chat_postMessage = AsyncMock()
    req = ApprovalRequest(
        session_id="missing",
        tool_name="Bash",
        tool_args={},
        request_id="r1",
        platform="slack",
    )
    await a._render_approval(req)
    a._web.chat_postMessage.assert_not_awaited()


def test_build_approval_blocks_shape() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="Write",
        tool_args={"path": "/etc/x"},
        request_id="rid-1",
        platform="slack",
    )
    text, blocks = SlackAdapter._build_approval_blocks(req)
    assert "Write" in text
    assert len(blocks) == 2
    assert blocks[1]["elements"][0]["style"] == "primary"
    assert blocks[1]["elements"][1]["style"] == "danger"


def test_build_approval_blocks_truncates_long_values() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="X",
        tool_args={"a": "y" * 5000},
        request_id="r",
        platform="slack",
    )
    _, blocks = SlackAdapter._build_approval_blocks(req)
    body = blocks[0]["text"]["text"]
    assert "…" in body
    assert len(body) < 1500


def test_build_approval_blocks_escapes_backticks() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="X",
        tool_args={"cmd": "echo `who`"},
        request_id="r",
        platform="slack",
    )
    _, blocks = SlackAdapter._build_approval_blocks(req)
    body = blocks[0]["text"]["text"]
    assert "ˋwhoˋ" in body


# ---- send_text / send_file / show_typing -----------------------------


async def test_send_text_calls_chat_postmessage(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()
    a._web.chat_postMessage = AsyncMock(return_value={"ts": "1.0"})
    out = await a.send_text("C1", "hello")
    assert out == "1.0"
    a._web.chat_postMessage.assert_awaited_once_with(channel="C1", text="hello")


async def test_send_text_before_start_raises(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    with pytest.raises(RuntimeError):
        await a.send_text("C1", "x")


async def test_send_file_uses_files_upload_v2(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._web = MagicMock()
    a._web.files_upload_v2 = AsyncMock(return_value={"file": {"id": "F99"}})
    f = tmp_path / "file.txt"
    f.write_text("payload")
    out = await a.send_file("C1", f, caption="check this")
    assert out == "F99"
    kwargs = a._web.files_upload_v2.await_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["file"] == str(f)
    assert kwargs["initial_comment"] == "check this"
    assert kwargs["filename"] == "file.txt"


async def test_send_file_before_start_raises(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    with pytest.raises(RuntimeError):
        await a.send_file("C1", tmp_path / "f")


async def test_show_typing_is_noop(tmp_path: Path) -> None:
    """Slack has no per-message typing for bot users; Phase 10.8
    instead uses an edit-status-message pattern. show_typing must
    not raise and not call any APIs."""
    a = _adapter(tmp_path)
    a._web = MagicMock()  # any attribute access would be caught
    result = await a.show_typing("C1")
    assert result is None


# ---- renderer cleanup on stop ----------------------------------------


async def test_stop_clears_platform_renderer(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.daemon.approvals.register_platform_renderer("slack", a._render_approval)
    a._socket = MagicMock()
    a._socket.disconnect = AsyncMock()
    a._web = MagicMock()
    a._web.close = AsyncMock()
    await a.stop()
    assert "slack" not in a.daemon.approvals.renderers
