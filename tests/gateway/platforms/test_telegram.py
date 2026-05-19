"""TelegramAdapter — aiogram wrapper.

aiogram's Bot/Dispatcher are heavy networked objects; these tests
substitute them with mocks. The adapter is shaped so the pieces that
actually need testing (event normalization, callback routing,
approval rendering, send helpers) are addressable without spinning
the polling loop.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from athena.gateway.events import ApprovalRequest, MessageEvent, MessageType
from athena.gateway.platforms.telegram import (
    _CALLBACK_PREFIX,
    _CALLBACK_SEPARATOR,
    TelegramAdapter,
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


def _adapter(tmp_path: Path) -> TelegramAdapter:
    daemon = _FakeDaemon(tmp_path)
    return TelegramAdapter(daemon, bot_token="test-token")


# ---- constructor ------------------------------------------------------


def test_construct_requires_bot_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        TelegramAdapter(_FakeDaemon(tmp_path), bot_token="")


def test_construct_sets_attachment_dir_under_profile(tmp_path: Path) -> None:
    daemon = _FakeDaemon(tmp_path)
    adapter = TelegramAdapter(daemon, bot_token="t")
    assert adapter.attachment_dir == daemon.profile_dir / "gateway_attachments" / "telegram"


def test_name_is_telegram(tmp_path: Path) -> None:
    assert _adapter(tmp_path).name == "telegram"


# ---- inbound event normalization --------------------------------------


def _stub_message(
    *,
    chat_id: int = 12345,
    chat_type: str = "private",
    user_id: int = 999,
    text: str | None = "hello",
    caption: str | None = None,
    message_id: int = 7,
    reply_to_id: int | None = None,
    photo=None,
    document=None,
    audio=None,
    voice=None,
    video=None,
    sticker=None,
):
    chat = SimpleNamespace(id=chat_id, type=chat_type)
    from_user = SimpleNamespace(id=user_id)
    reply_to_message = SimpleNamespace(message_id=reply_to_id) if reply_to_id else None
    return SimpleNamespace(
        chat=chat,
        from_user=from_user,
        text=text,
        caption=caption,
        message_id=message_id,
        reply_to_message=reply_to_message,
        photo=photo,
        document=document,
        audio=audio,
        voice=voice,
        video=video,
        sticker=sticker,
    )


async def test_event_from_text_message(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_message(_stub_message())
    assert event.platform == "telegram"
    assert event.chat_id == "12345"
    assert event.user_id == "999"
    assert event.text == "hello"
    assert event.message_type == MessageType.TEXT
    assert event.is_dm is True
    assert event.platform_message_id == "7"
    assert event.reply_to_message_id is None
    assert event.attachments == []


async def test_group_chat_marked_not_dm(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_message(_stub_message(chat_type="supergroup"))
    assert event.is_dm is False


async def test_reply_to_message_id_preserved(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_message(_stub_message(reply_to_id=42))
    assert event.reply_to_message_id == "42"


async def test_photo_message_classified_with_caption(tmp_path: Path) -> None:
    """A photo with a caption: text comes from caption, type is PHOTO,
    the largest photo gets downloaded into the attachment cache."""
    a = _adapter(tmp_path)
    # aiogram exposes photo as a list of PhotoSize, largest last.
    photo = [
        SimpleNamespace(file_id="tiny", file_unique_id="ut"),
        SimpleNamespace(file_id="biggest", file_unique_id="ub"),
    ]
    msg = _stub_message(text=None, caption="look at this", photo=photo)
    # Stub the download path.
    a._bot = MagicMock()
    a._bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="photos/abc.jpg"))
    a._bot.download_file = AsyncMock()

    event = await a._event_from_message(msg)
    assert event.text == "look at this"
    assert event.message_type == MessageType.PHOTO
    # Only the biggest size gets downloaded.
    a._bot.get_file.assert_awaited_once_with("biggest")
    assert len(event.attachments) == 1
    assert event.attachments[0].name.startswith("photo-ub")


async def test_sticker_classified_with_emoji_text(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    sticker = SimpleNamespace(emoji="🎉", file_id="x", file_unique_id="us")
    msg = _stub_message(text=None, sticker=sticker)
    event = await a._event_from_message(msg)
    assert event.message_type == MessageType.STICKER
    assert event.text == "🎉"


async def test_voice_message_classified_audio(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    voice = SimpleNamespace(file_id="vid", file_unique_id="uv")
    msg = _stub_message(text=None, voice=voice)
    a._bot = MagicMock()
    a._bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="voice/abc.ogg"))
    a._bot.download_file = AsyncMock()
    event = await a._event_from_message(msg)
    assert event.message_type == MessageType.AUDIO


async def test_document_attachment_uses_provided_filename(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    doc = SimpleNamespace(file_id="dx", file_name="report.pdf")
    msg = _stub_message(text=None, caption="please review", document=doc)
    a._bot = MagicMock()
    a._bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="docs/report.pdf"))
    a._bot.download_file = AsyncMock()
    event = await a._event_from_message(msg)
    assert event.message_type == MessageType.DOCUMENT
    assert event.text == "please review"
    assert event.attachments[0].name == "report.pdf"


async def test_download_failure_skips_one_attachment(tmp_path: Path) -> None:
    """A single download failure must not break the whole event."""
    a = _adapter(tmp_path)
    photo = [SimpleNamespace(file_id="big", file_unique_id="ub")]
    msg = _stub_message(text=None, caption="oops", photo=photo)
    a._bot = MagicMock()
    a._bot.get_file = AsyncMock(side_effect=RuntimeError("server down"))
    event = await a._event_from_message(msg)
    # Caption still arrives even though the download blew up.
    assert event.text == "oops"
    assert event.attachments == []


# ---- _on_message routing through handle_inbound ----------------------


async def test_on_message_routes_through_handle_inbound(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    # Replace handle_inbound with a spy so we don't recurse into the
    # full base orchestration here (that's tested separately).
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    msg = _stub_message(text="hi")
    await a._on_message(msg)
    a.handle_inbound.assert_awaited_once()
    event = a.handle_inbound.await_args.args[0]
    assert event.text == "hi"


async def test_on_message_swallows_normalization_exception(
    tmp_path: Path,
) -> None:
    """If _event_from_message raises, _on_message must NOT propagate
    or aiogram's dispatcher will mark the update unhandled and retry."""
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]

    async def bad(_msg):
        raise RuntimeError("broken")

    a._event_from_message = bad  # type: ignore[assignment]
    # Must not raise.
    await a._on_message(_stub_message())
    a.handle_inbound.assert_not_awaited()


# ---- callback (approval button click) -------------------------------


async def test_callback_routes_allow_to_approvals(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    cb = SimpleNamespace(
        data=_CALLBACK_SEPARATOR.join((_CALLBACK_PREFIX, "abc123", "allow")),
        answer=AsyncMock(),
    )
    await a._on_callback(cb)
    assert a.daemon.approvals.resolves == [("abc123", "allow")]
    cb.answer.assert_awaited_once()


async def test_callback_routes_deny(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    cb = SimpleNamespace(
        data=f"{_CALLBACK_PREFIX}:abc:deny",
        answer=AsyncMock(),
    )
    await a._on_callback(cb)
    assert a.daemon.approvals.resolves == [("abc", "deny")]


async def test_callback_ignores_unknown_prefix(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    cb = SimpleNamespace(data="other:data", answer=AsyncMock())
    await a._on_callback(cb)
    assert a.daemon.approvals.resolves == []
    cb.answer.assert_awaited_once()


async def test_callback_ignores_unknown_decision(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    cb = SimpleNamespace(data=f"{_CALLBACK_PREFIX}:r:nope", answer=AsyncMock())
    await a._on_callback(cb)
    assert a.daemon.approvals.resolves == []


async def test_callback_answer_exception_is_swallowed(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    cb = SimpleNamespace(
        data=f"{_CALLBACK_PREFIX}:r:allow",
        answer=AsyncMock(side_effect=RuntimeError("network")),
    )
    # Must not raise — the resolve already happened.
    await a._on_callback(cb)
    assert a.daemon.approvals.resolves == [("r", "allow")]


# ---- approval rendering ---------------------------------------------


async def test_render_approval_uses_explicit_chat_id_when_set(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a._bot = MagicMock()
    a._bot.send_message = AsyncMock()
    req = ApprovalRequest(
        session_id="s1",
        tool_name="Bash",
        tool_args={"cmd": "ls"},
        request_id="r1",
        platform="telegram",
        chat_id="42",
    )
    await a._render_approval(req)
    a._bot.send_message.assert_awaited_once()
    args, kwargs = a._bot.send_message.await_args
    assert args[0] == "42"
    assert "Bash" in args[1]
    assert "ls" in args[1]
    assert kwargs.get("reply_markup") is not None


async def test_render_approval_falls_back_to_router_route(
    tmp_path: Path,
) -> None:
    """When chat_id isn't set on the request, find it via the
    router's most-recently-seen Telegram route for the session."""
    from datetime import datetime, timedelta, timezone

    a = _adapter(tmp_path)
    a._bot = MagicMock()
    a._bot.send_message = AsyncMock()

    now = datetime.now(timezone.utc)
    a.daemon.router.routes = [
        SimpleNamespace(
            session_id="s1",
            chat_id="older",
            last_seen_at=now - timedelta(hours=1),
            platform="telegram",
        ),
        SimpleNamespace(
            session_id="s1",
            chat_id="newest",
            last_seen_at=now,
            platform="telegram",
        ),
    ]

    req = ApprovalRequest(
        session_id="s1",
        tool_name="Bash",
        tool_args={},
        request_id="r1",
        platform="telegram",
    )
    await a._render_approval(req)
    args, _ = a._bot.send_message.await_args
    assert args[0] == "newest"


async def test_render_approval_drops_when_no_route(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._bot = MagicMock()
    a._bot.send_message = AsyncMock()
    req = ApprovalRequest(
        session_id="missing",
        tool_name="Bash",
        tool_args={},
        request_id="r1",
        platform="telegram",
    )
    await a._render_approval(req)
    a._bot.send_message.assert_not_awaited()


def test_build_approval_keyboard_shape() -> None:
    kb = TelegramAdapter._build_approval_keyboard("abc123")
    # aiogram InlineKeyboardMarkup carries inline_keyboard: list[list[btn]].
    rows = kb.inline_keyboard
    assert len(rows) == 1
    allow_btn, deny_btn = rows[0]
    assert allow_btn.callback_data == f"{_CALLBACK_PREFIX}:abc123:allow"
    assert deny_btn.callback_data == f"{_CALLBACK_PREFIX}:abc123:deny"


def test_format_approval_body_truncates_long_arg_values() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="Write",
        tool_args={"content": "x" * 5000},
        request_id="r",
        platform="telegram",
    )
    body = TelegramAdapter._format_approval_body(req)
    assert "Write" in body
    assert "…" in body
    # Stays well under Telegram's 4096 char cap.
    assert len(body) < 1000


def test_format_approval_body_escapes_backticks() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="Bash",
        tool_args={"cmd": "echo `whoami`"},
        request_id="r",
        platform="telegram",
    )
    body = TelegramAdapter._format_approval_body(req)
    # Markdown-fenced code shouldn't be broken by user-supplied backticks.
    assert "ˋwhoamiˋ" in body


def test_format_approval_body_with_no_args() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="Status",
        tool_args={},
        request_id="r",
        platform="telegram",
    )
    body = TelegramAdapter._format_approval_body(req)
    assert body == "⚠ Run `Status`?"


# ---- send_text / send_file --------------------------------------------


async def test_send_text_calls_bot(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._bot = MagicMock()
    a._bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=99))
    out = await a.send_text("chat-1", "hello world")
    assert out == "99"
    a._bot.send_message.assert_awaited_once_with(
        "chat-1",
        "hello world",
        parse_mode="Markdown",
    )


async def test_send_text_before_start_raises(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    with pytest.raises(RuntimeError):
        await a.send_text("c", "t")


async def test_send_file_uses_fsinputfile(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._bot = MagicMock()
    a._bot.send_document = AsyncMock(return_value=SimpleNamespace(message_id=33))
    f = tmp_path / "test.txt"
    f.write_text("hi")
    out = await a.send_file("chat-1", f, caption="my file")
    assert out == "33"
    a._bot.send_document.assert_awaited_once()
    args, kwargs = a._bot.send_document.await_args
    assert args[0] == "chat-1"
    # FSInputFile carries path; check it points at our temp file.
    file_arg = args[1]
    assert str(f) in str(getattr(file_arg, "path", ""))
    assert kwargs.get("caption") == "my file"


async def test_show_typing_calls_chat_action(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._bot = MagicMock()
    a._bot.send_chat_action = AsyncMock()
    await a.show_typing("chat-1")
    a._bot.send_chat_action.assert_awaited_once_with("chat-1", "typing")


async def test_show_typing_swallows_errors(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._bot = MagicMock()
    a._bot.send_chat_action = AsyncMock(side_effect=RuntimeError("rate limit"))
    # Must not raise — typing indicators are best-effort.
    await a.show_typing("chat-1")


# ---- approval-renderer registration on start/stop --------------------


async def test_stop_clears_platform_renderer(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    # Pretend start() ran enough to register the renderer.
    a.daemon.approvals.register_platform_renderer("telegram", a._render_approval)
    # Stub the bot bits stop() touches.
    a._bot = MagicMock()
    a._bot.session = MagicMock()
    a._bot.session.close = AsyncMock()
    a._dp = MagicMock()
    a._dp.stop_polling = AsyncMock()
    await a.stop()
    assert "telegram" not in a.daemon.approvals.renderers
