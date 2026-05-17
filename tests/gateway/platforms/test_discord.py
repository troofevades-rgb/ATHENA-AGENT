"""DiscordAdapter — discord.py wrapper.

discord.py's Client + ui.View live deep inside their own asyncio /
gateway machinery. We mock the surface at the points the adapter
interacts with it: Channel-like objects, Message-like objects, and
Interaction-like objects. The adapter is shaped so the testable bits
(event normalization, approval rendering, send helpers) are
addressable without spinning a real gateway connection.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from athena.gateway.events import ApprovalRequest, MessageEvent, MessageType
from athena.gateway.platforms.discord import (
    DiscordAdapter,
    _build_approval_view,
    _format_approval_body,
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


def _adapter(tmp_path: Path) -> DiscordAdapter:
    return DiscordAdapter(_FakeDaemon(tmp_path), bot_token="discord-token")


def _stub_text_channel(channel_id: int = 100, *, is_dm: bool = False):
    """Object that quacks like discord.TextChannel / DMChannel."""
    if is_dm:
        ch = MagicMock(spec=discord.DMChannel)
    else:
        ch = MagicMock(spec=discord.TextChannel)
    ch.id = channel_id
    ch.send = AsyncMock()
    return ch


def _stub_message(
    *,
    content: str = "hello",
    channel=None,
    author_id: int = 1000,
    author_bot: bool = False,
    message_id: int = 555,
    reference_id: int | None = None,
    attachments=None,
):
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.id = message_id
    msg.channel = channel if channel is not None else _stub_text_channel()
    msg.author = SimpleNamespace(id=author_id, bot=author_bot)
    if reference_id is not None:
        msg.reference = SimpleNamespace(message_id=reference_id)
    else:
        msg.reference = None
    msg.attachments = list(attachments or [])
    return msg


# ---- constructor ------------------------------------------------------


def test_construct_requires_bot_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        DiscordAdapter(_FakeDaemon(tmp_path), bot_token="")


def test_name_is_discord(tmp_path: Path) -> None:
    assert _adapter(tmp_path).name == "discord"


def test_default_attachment_dir_under_profile(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert a.attachment_dir == a.daemon.profile_dir / "gateway_attachments" / "discord"


# ---- event normalization ---------------------------------------------


async def test_text_dm_message_event(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    msg = _stub_message(channel=_stub_text_channel(99, is_dm=True))
    event = await a._event_from_message(msg)
    assert event.platform == "discord"
    assert event.chat_id == "99"
    assert event.user_id == "1000"
    assert event.text == "hello"
    assert event.is_dm is True
    assert event.message_type == MessageType.TEXT
    assert event.platform_message_id == "555"


async def test_guild_channel_message_is_not_dm(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    msg = _stub_message(channel=_stub_text_channel(99, is_dm=False))
    event = await a._event_from_message(msg)
    assert event.is_dm is False


async def test_reply_reference_preserved(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    msg = _stub_message(reference_id=42)
    event = await a._event_from_message(msg)
    assert event.reply_to_message_id == "42"


async def test_image_attachment_classifies_as_photo(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    att = MagicMock()
    att.filename = "pic.png"
    att.content_type = "image/png"
    att.id = 77
    att.save = AsyncMock()
    msg = _stub_message(content="look", attachments=[att])
    event = await a._event_from_message(msg)
    assert event.message_type == MessageType.PHOTO
    assert event.text == "look"
    assert len(event.attachments) == 1
    assert event.attachments[0].name == "pic.png"
    att.save.assert_awaited_once()


async def test_audio_attachment_classifies(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    att = MagicMock(filename="v.mp3", content_type="audio/mpeg", id=1)
    att.save = AsyncMock()
    msg = _stub_message(attachments=[att])
    event = await a._event_from_message(msg)
    assert event.message_type == MessageType.AUDIO


async def test_video_attachment_classifies(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    att = MagicMock(filename="v.mp4", content_type="video/mp4", id=1)
    att.save = AsyncMock()
    msg = _stub_message(attachments=[att])
    event = await a._event_from_message(msg)
    assert event.message_type == MessageType.VIDEO


async def test_unknown_attachment_mime_classifies_as_document(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    att = MagicMock(filename="r.pdf", content_type="application/pdf", id=1)
    att.save = AsyncMock()
    msg = _stub_message(attachments=[att])
    event = await a._event_from_message(msg)
    assert event.message_type == MessageType.DOCUMENT


async def test_attachment_save_failure_per_file(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    bad = MagicMock(filename="bad.png", content_type="image/png", id=1)
    bad.save = AsyncMock(side_effect=RuntimeError("network"))
    good = MagicMock(filename="ok.png", content_type="image/png", id=2)
    good.save = AsyncMock()
    msg = _stub_message(attachments=[bad, good])
    event = await a._event_from_message(msg)
    # Bad one is skipped; good one made it.
    names = [p.name for p in event.attachments]
    assert names == ["ok.png"]


async def test_attachment_no_save_method_skipped(tmp_path: Path) -> None:
    """Defensive: if discord.py changes Attachment, the adapter must
    skip gracefully rather than AttributeError-ing the whole event."""
    a = _adapter(tmp_path)
    att = MagicMock()
    att.filename = "x.bin"
    att.content_type = "application/octet-stream"
    att.id = 1
    att.save = None
    msg = _stub_message(attachments=[att])
    event = await a._event_from_message(msg)
    assert event.attachments == []
    assert event.message_type == MessageType.DOCUMENT


# ---- _on_message filtering -------------------------------------------


async def test_on_message_skips_own_bot_message(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a._client = MagicMock()
    a._client.user = SimpleNamespace(id=1000)
    # Our bot's id == author's id → skip.
    msg = _stub_message(author_id=1000)
    await a._on_message(msg)
    a.handle_inbound.assert_not_awaited()


async def test_on_message_skips_other_bots(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a._client = MagicMock()
    a._client.user = SimpleNamespace(id=1000)
    msg = _stub_message(author_id=2000, author_bot=True)
    await a._on_message(msg)
    a.handle_inbound.assert_not_awaited()


async def test_on_message_routes_human_messages(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a._client = MagicMock()
    a._client.user = SimpleNamespace(id=1000)
    msg = _stub_message(author_id=2000, author_bot=False, content="hi human")
    await a._on_message(msg)
    a.handle_inbound.assert_awaited_once()


async def test_on_message_swallows_normalization_exception(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a._client = MagicMock()
    a._client.user = SimpleNamespace(id=1000)

    async def bad(_m):
        raise RuntimeError("broken")

    a._event_from_message = bad  # type: ignore[assignment]
    await a._on_message(_stub_message(author_id=2000))
    a.handle_inbound.assert_not_awaited()


# ---- slash command --------------------------------------------------


async def test_slash_command_routes_through_handle_inbound(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    interaction = MagicMock()
    interaction.id = 12345
    interaction.user = SimpleNamespace(id=42)
    interaction.channel = _stub_text_channel(99, is_dm=True)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    await a._on_slash_command(interaction, prompt="hello via /athena")
    interaction.response.defer.assert_awaited_once()
    a.handle_inbound.assert_awaited_once()
    event = a.handle_inbound.await_args.args[0]
    assert event.text == "hello via /athena"
    assert event.raw == {"via": "slash_command"}


async def test_slash_defer_failure_does_not_block_inbound(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    interaction = MagicMock()
    interaction.id = 1
    interaction.user = SimpleNamespace(id=42)
    interaction.channel = _stub_text_channel(99)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock(side_effect=RuntimeError("timeout"))
    await a._on_slash_command(interaction, prompt="x")
    a.handle_inbound.assert_awaited_once()


# ---- approval rendering ---------------------------------------------


async def test_render_approval_sends_view_to_channel(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    channel = _stub_text_channel(42)
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=channel)
    req = ApprovalRequest(
        session_id="s1", tool_name="Bash", tool_args={"cmd": "ls"},
        request_id="r1", platform="discord", chat_id="42",
    )
    await a._render_approval(req)
    channel.send.assert_awaited_once()
    args, kwargs = channel.send.await_args
    body = args[0]
    assert "Bash" in body
    assert "ls" in body
    assert kwargs.get("view") is not None


async def test_render_approval_falls_back_to_router_route(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timedelta, timezone

    a = _adapter(tmp_path)
    channel = _stub_text_channel(7)
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=channel)
    now = datetime.now(timezone.utc)
    a.daemon.router.routes = [
        SimpleNamespace(
            session_id="s1", chat_id="5", platform="discord",
            last_seen_at=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            session_id="s1", chat_id="7", platform="discord",
            last_seen_at=now,
        ),
    ]
    req = ApprovalRequest(
        session_id="s1", tool_name="Bash", tool_args={},
        request_id="r1", platform="discord",
    )
    await a._render_approval(req)
    a._client.get_channel.assert_called_once_with(7)
    channel.send.assert_awaited_once()


async def test_render_approval_drops_when_no_route(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    channel = _stub_text_channel(42)
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=channel)
    req = ApprovalRequest(
        session_id="missing", tool_name="Bash", tool_args={},
        request_id="r1", platform="discord",
    )
    await a._render_approval(req)
    channel.send.assert_not_awaited()


async def test_render_approval_falls_back_to_fetch_channel(
    tmp_path: Path,
) -> None:
    """When the channel isn't in cache, fetch_channel is the next try."""
    a = _adapter(tmp_path)
    fetched = _stub_text_channel(99)
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=None)
    a._client.fetch_channel = AsyncMock(return_value=fetched)
    req = ApprovalRequest(
        session_id="s", tool_name="Bash", tool_args={},
        request_id="r", platform="discord", chat_id="99",
    )
    await a._render_approval(req)
    a._client.fetch_channel.assert_awaited_once_with(99)
    fetched.send.assert_awaited_once()


# ---- approval body & view helpers -----------------------------------


def test_format_approval_body_truncates_long_values() -> None:
    req = ApprovalRequest(
        session_id="s", tool_name="X", tool_args={"big": "Y" * 5000},
        request_id="r", platform="discord",
    )
    body = _format_approval_body(req)
    # Discord cap is 2000; we stay well under.
    assert len(body) < 800
    assert "…" in body


def test_format_approval_body_escapes_triple_backticks() -> None:
    req = ApprovalRequest(
        session_id="s", tool_name="X", tool_args={"code": "```bash\nrm -rf"},
        request_id="r", platform="discord",
    )
    body = _format_approval_body(req)
    assert "```" not in body.split("⚠")[1]


def test_format_approval_body_no_args() -> None:
    req = ApprovalRequest(
        session_id="s", tool_name="Status", tool_args={},
        request_id="r", platform="discord",
    )
    assert _format_approval_body(req) == "⚠ Run `Status`?"


def test_build_approval_view_has_two_buttons() -> None:
    captured: list[tuple[str, str]] = []

    def on_decision(rid: str, decision: str) -> None:
        captured.append((rid, decision))

    view = _build_approval_view("rid-x", on_decision=on_decision, timeout=30.0)
    children = view.children
    assert len(children) == 2
    labels = sorted(c.label for c in children)
    assert labels == ["✅ Allow", "✖ Deny"]


async def test_approval_view_button_resolves_via_callback(
    tmp_path: Path,
) -> None:
    """Click → on_decision invoked with the (request_id, decision)
    pair → buttons disabled → view stopped."""
    calls: list[tuple[str, str]] = []

    def on_decision(rid: str, decision: str) -> None:
        calls.append((rid, decision))

    view = _build_approval_view("rid-x", on_decision=on_decision, timeout=30.0)
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    allow = view.children[0]
    await allow.callback(interaction)
    assert calls == [("rid-x", "allow")]
    interaction.response.send_message.assert_awaited_once()
    assert all(getattr(c, "disabled", False) for c in view.children)


async def test_approval_view_deny_button(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    view = _build_approval_view(
        "r", on_decision=lambda rid, d: calls.append((rid, d)), timeout=10.0,
    )
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    deny = view.children[1]
    await deny.callback(interaction)
    assert calls == [("r", "deny")]


# ---- send_text / send_file / show_typing ----------------------------


async def test_send_text_uses_channel_send(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    channel = _stub_text_channel(1)
    channel.send = AsyncMock(return_value=SimpleNamespace(id=999))
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=channel)
    out = await a.send_text("1", "hello")
    assert out == "999"
    channel.send.assert_awaited_once_with("hello")


async def test_send_text_unresolvable_channel_raises(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=None)
    a._client.fetch_channel = AsyncMock(side_effect=Exception("not found"))
    with pytest.raises(Exception):
        await a.send_text("1", "hello")


async def test_send_file_uses_discord_File(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    channel = _stub_text_channel(1)
    channel.send = AsyncMock(return_value=SimpleNamespace(id=42))
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=channel)
    f = tmp_path / "x.txt"
    f.write_text("payload")
    out = await a.send_file("1", f, caption="see attached")
    assert out == "42"
    kwargs = channel.send.await_args.kwargs
    assert kwargs["content"] == "see attached"
    assert isinstance(kwargs["file"], discord.File)


async def test_show_typing_enters_context(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    channel = _stub_text_channel(1)
    entered: list[bool] = []
    exited: list[bool] = []

    class _Typing:
        async def __aenter__(self):
            entered.append(True)
            return self

        async def __aexit__(self, *exc):
            exited.append(True)
            return False

    channel.typing = MagicMock(return_value=_Typing())
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=channel)
    await a.show_typing("1")
    assert entered == [True]
    assert exited == [True]


async def test_show_typing_swallows_errors(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=None)
    a._client.fetch_channel = AsyncMock(side_effect=Exception("bad"))
    # Must not raise even when channel resolution fails.
    await a.show_typing("not-a-number")


async def test_show_typing_no_channel_returns_silently(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.get_channel = MagicMock(return_value=None)
    a._client.fetch_channel = AsyncMock(return_value=None)
    await a.show_typing("1")  # No exception.


# ---- approval-button helper invokes daemon.approvals -----------------


async def test_on_approval_button_forwards_decision(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    await a._on_approval_button("rid-1", "allow")
    assert a.daemon.approvals.resolves == [("rid-1", "allow")]


async def test_on_approval_button_ignores_unknown_decision(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    await a._on_approval_button("rid-1", "burn-it")
    assert a.daemon.approvals.resolves == []


# ---- renderer cleanup ------------------------------------------------


async def test_stop_clears_platform_renderer(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.daemon.approvals.register_platform_renderer("discord", a._render_approval)
    a._client = MagicMock()
    a._client.close = AsyncMock()
    await a.stop()
    assert "discord" not in a.daemon.approvals.renderers
