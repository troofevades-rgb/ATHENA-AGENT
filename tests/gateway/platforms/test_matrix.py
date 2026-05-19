"""MatrixAdapter — matrix-nio wrapper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from athena.gateway.events import ApprovalRequest
from athena.gateway.platforms.matrix import (
    MatrixAdapter,
    _e2e_available,
    _format_approval_body,
    _msgtype_for_mime,
)


class _FakeRouter:
    def __init__(self) -> None:
        self.calls = []
        self.routes: list = []

    async def resolve(self, event):
        self.calls.append(event)
        return "sess-1"

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

    def resolve(self, request_id, decision):
        self.resolves.append((request_id, decision))
        return True


class _FakeDaemon:
    def __init__(self, tmp_path: Path) -> None:
        self.router = _FakeRouter()
        self.approvals = _FakeApprovals()
        self.profile_dir = tmp_path / "profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)


def _adapter(tmp_path: Path, **overrides) -> MatrixAdapter:
    defaults = dict(
        homeserver="https://matrix.example.org",
        user_id="@bot:example.org",
        access_token="syt_TOKEN",
        device_id="DEV1",
    )
    defaults.update(overrides)
    return MatrixAdapter(_FakeDaemon(tmp_path), **defaults)


# ---- constructor ----------------------------------------------------


def test_construct_requires_homeserver(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MatrixAdapter(
            _FakeDaemon(tmp_path),
            homeserver="",
            user_id="@b:x",
            access_token="t",
            device_id="D",
        )


def test_construct_validates_user_id_format(tmp_path: Path) -> None:
    """MXID must start with @."""
    with pytest.raises(ValueError):
        MatrixAdapter(
            _FakeDaemon(tmp_path),
            homeserver="https://x",
            user_id="bot:x",
            access_token="t",
            device_id="D",
        )


def test_construct_requires_access_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MatrixAdapter(
            _FakeDaemon(tmp_path),
            homeserver="https://x",
            user_id="@b:x",
            access_token="",
            device_id="D",
        )


def test_construct_requires_device_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MatrixAdapter(
            _FakeDaemon(tmp_path),
            homeserver="https://x",
            user_id="@b:x",
            access_token="t",
            device_id="",
        )


def test_name_is_matrix(tmp_path: Path) -> None:
    assert _adapter(tmp_path).name == "matrix"


def test_store_path_defaults_under_profile(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert a.store_path == a.daemon.profile_dir / "matrix_store"
    assert a.store_path.exists()


def test_homeserver_trailing_slash_stripped(tmp_path: Path) -> None:
    a = _adapter(tmp_path, homeserver="https://matrix.example.org/")
    assert a.homeserver == "https://matrix.example.org"


# ---- event normalization --------------------------------------------


def test_event_from_room_message_dm(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    room = SimpleNamespace(
        room_id="!room:server",
        users={"@bot:example.org": None, "@alice:example.org": None},
    )
    event = SimpleNamespace(
        sender="@alice:example.org",
        body="hello",
        event_id="$evt-1",
    )
    mev = a._event_from_room_message(room, event)
    assert mev.platform == "matrix"
    assert mev.chat_id == "!room:server"
    assert mev.user_id == "@alice:example.org"
    assert mev.text == "hello"
    assert mev.is_dm is True
    assert mev.platform_message_id == "$evt-1"


def test_event_from_room_message_public_room_not_dm(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    room = SimpleNamespace(
        room_id="!room:server",
        users={
            "@bot:example.org": None,
            "@alice:example.org": None,
            "@bob:example.org": None,
        },
    )
    event = SimpleNamespace(sender="@alice:example.org", body="hi", event_id="$e")
    mev = a._event_from_room_message(room, event)
    assert mev.is_dm is False


# ---- _on_message ----------------------------------------------------


async def test_on_message_routes_to_handle_inbound(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    room = SimpleNamespace(room_id="!r", users={"@bot:example.org": None, "@a:x": None})
    event = SimpleNamespace(sender="@a:x", body="hi", event_id="$1")
    await a._on_message(room, event)
    a.handle_inbound.assert_awaited_once()


async def test_on_message_skips_own_echo(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    room = SimpleNamespace(room_id="!r", users={})
    event = SimpleNamespace(sender="@bot:example.org", body="echo", event_id="$2")
    await a._on_message(room, event)
    a.handle_inbound.assert_not_awaited()


async def test_on_message_swallows_normalize_exception(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]

    def boom(*_a, **_kw):
        raise RuntimeError("broken")

    a._event_from_room_message = boom  # type: ignore[assignment]
    await a._on_message(
        SimpleNamespace(room_id="!r", users={}),
        SimpleNamespace(sender="@a:x", body="x", event_id="$x"),
    )
    a.handle_inbound.assert_not_awaited()


# ---- reaction target extraction ------------------------------------


def test_reaction_target_via_reacts_to_attr() -> None:
    event = SimpleNamespace(key="✅", reacts_to="$prompt-1")
    out = MatrixAdapter._reaction_target(event)
    assert out == ("$prompt-1", "✅")


def test_reaction_target_via_source_raw() -> None:
    """Some matrix-nio versions only expose the relation in source."""
    event = SimpleNamespace(
        key=None,
        reacts_to=None,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$prompt-2",
                    "key": "✖",
                }
            }
        },
    )
    out = MatrixAdapter._reaction_target(event)
    assert out == ("$prompt-2", "✖")


def test_reaction_target_returns_none_for_unrelated() -> None:
    """No target = not a reaction relating to a known event."""
    event = SimpleNamespace(key="✅", reacts_to=None, source={"content": {}})
    assert MatrixAdapter._reaction_target(event) is None


def test_reaction_target_non_string_key_rejected() -> None:
    event = SimpleNamespace(key=42, reacts_to="$x")
    assert MatrixAdapter._reaction_target(event) is None


# ---- _on_reaction --------------------------------------------------


async def test_reaction_allow_resolves_pending(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._prompt_to_request["$prompt-1"] = "rid-1"
    event = SimpleNamespace(
        sender="@alice:x",
        key="✅",
        reacts_to="$prompt-1",
    )
    await a._on_reaction(SimpleNamespace(), event)
    assert a.daemon.approvals.resolves == [("rid-1", "allow")]
    # Mapping cleared so a double-tap doesn't double-resolve.
    assert "$prompt-1" not in a._prompt_to_request


async def test_reaction_deny_resolves_pending(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._prompt_to_request["$prompt-2"] = "rid-2"
    event = SimpleNamespace(
        sender="@alice:x",
        key="✖",
        reacts_to="$prompt-2",
    )
    await a._on_reaction(SimpleNamespace(), event)
    assert a.daemon.approvals.resolves == [("rid-2", "deny")]


async def test_reaction_unknown_emoji_ignored(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._prompt_to_request["$prompt-x"] = "rid-x"
    event = SimpleNamespace(
        sender="@alice:x",
        key="🎉",
        reacts_to="$prompt-x",
    )
    await a._on_reaction(SimpleNamespace(), event)
    assert a.daemon.approvals.resolves == []
    # Mapping not cleared — user may tap allow/deny next.
    assert a._prompt_to_request.get("$prompt-x") == "rid-x"


async def test_reaction_from_own_user_ignored(tmp_path: Path) -> None:
    """We pre-seed reactions ourselves; we mustn't resolve on those."""
    a = _adapter(tmp_path)
    a._prompt_to_request["$prompt-3"] = "rid-3"
    event = SimpleNamespace(
        sender="@bot:example.org",
        key="✅",
        reacts_to="$prompt-3",
    )
    await a._on_reaction(SimpleNamespace(), event)
    assert a.daemon.approvals.resolves == []
    assert "$prompt-3" in a._prompt_to_request


async def test_reaction_to_unknown_prompt_ignored(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = SimpleNamespace(
        sender="@a:x",
        key="✅",
        reacts_to="$random-event",
    )
    await a._on_reaction(SimpleNamespace(), event)
    assert a.daemon.approvals.resolves == []


# ---- approval rendering -------------------------------------------


async def test_render_approval_sends_prompt_and_seeds_reactions(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.room_send = AsyncMock(return_value=SimpleNamespace(event_id="$prompt-X"))
    req = ApprovalRequest(
        session_id="s1",
        tool_name="Bash",
        tool_args={"cmd": "ls"},
        request_id="rid-Q",
        platform="matrix",
        chat_id="!room:x",
    )
    await a._render_approval(req)
    # Three room_send calls: prompt + two reactions.
    assert a._client.room_send.await_count == 3
    # Prompt-to-request mapping populated using the prompt's event_id.
    assert a._prompt_to_request == {"$prompt-X": "rid-Q"}


async def test_render_approval_falls_back_to_router_route(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timedelta, timezone

    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.room_send = AsyncMock(return_value=SimpleNamespace(event_id="$p"))
    now = datetime.now(timezone.utc)
    a.daemon.router.routes = [
        SimpleNamespace(
            session_id="s1",
            chat_id="!old:x",
            platform="matrix",
            last_seen_at=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            session_id="s1",
            chat_id="!new:x",
            platform="matrix",
            last_seen_at=now,
        ),
    ]
    req = ApprovalRequest(
        session_id="s1",
        tool_name="X",
        tool_args={},
        request_id="r",
        platform="matrix",
    )
    await a._render_approval(req)
    first_call = a._client.room_send.await_args_list[0]
    assert first_call.kwargs["room_id"] == "!new:x"


async def test_render_approval_no_route_skips(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.room_send = AsyncMock()
    req = ApprovalRequest(
        session_id="missing",
        tool_name="X",
        tool_args={},
        request_id="r",
        platform="matrix",
    )
    await a._render_approval(req)
    a._client.room_send.assert_not_awaited()


async def test_render_approval_swallows_seed_failure(tmp_path: Path) -> None:
    """If seeding one of the reactions fails, the prompt was already
    sent successfully — don't undo it."""
    a = _adapter(tmp_path)
    a._client = MagicMock()
    call_count = 0

    async def side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return SimpleNamespace(event_id="$prompt")
        raise RuntimeError("rate limited")

    a._client.room_send = side
    req = ApprovalRequest(
        session_id="s",
        tool_name="X",
        tool_args={},
        request_id="r",
        platform="matrix",
        chat_id="!r:x",
    )
    await a._render_approval(req)
    # Prompt mapping still recorded even though reaction seeds failed.
    assert a._prompt_to_request == {"$prompt": "r"}


# ---- outbound -----------------------------------------------------


async def test_send_text_returns_event_id(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.room_send = AsyncMock(return_value=SimpleNamespace(event_id="$out-1"))
    out = await a.send_text("!r:x", "hello there")
    assert out == "$out-1"
    kwargs = a._client.room_send.await_args.kwargs
    assert kwargs["room_id"] == "!r:x"
    assert kwargs["message_type"] == "m.room.message"
    assert kwargs["content"]["body"] == "hello there"


async def test_send_text_before_start_raises(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    with pytest.raises(RuntimeError):
        await a.send_text("!r:x", "hi")


async def test_show_typing_calls_room_typing(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.room_typing = AsyncMock()
    await a.show_typing("!r:x")
    a._client.room_typing.assert_awaited_once_with(
        "!r:x",
        typing_state=True,
        timeout=4000,
    )


async def test_show_typing_swallows_failure(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.room_typing = AsyncMock(side_effect=Exception("rate"))
    # Must not raise.
    await a.show_typing("!r:x")


# ---- helpers ------------------------------------------------------


def test_msgtype_for_mime_buckets() -> None:
    assert _msgtype_for_mime("image/png") == "m.image"
    assert _msgtype_for_mime("audio/ogg") == "m.audio"
    assert _msgtype_for_mime("video/mp4") == "m.video"
    assert _msgtype_for_mime("application/pdf") == "m.file"
    assert _msgtype_for_mime("text/plain") == "m.file"


def test_format_approval_body_no_args() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="X",
        tool_args={},
        request_id="r",
        platform="matrix",
    )
    body = _format_approval_body(req)
    assert "X" in body
    assert "✅" in body and "✖" in body


def test_format_approval_body_truncates() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="Y",
        tool_args={"big": "z" * 5000},
        request_id="r",
        platform="matrix",
    )
    body = _format_approval_body(req)
    assert "…" in body
    assert len(body) < 1000


def test_format_approval_body_escapes_backticks() -> None:
    req = ApprovalRequest(
        session_id="s",
        tool_name="Z",
        tool_args={"x": "echo `whoami`"},
        request_id="r",
        platform="matrix",
    )
    body = _format_approval_body(req)
    assert "ˋwhoamiˋ" in body


def test_e2e_available_is_bool() -> None:
    """Just verify the helper doesn't blow up; the actual value
    depends on whether python-olm is installed."""
    assert isinstance(_e2e_available(), bool)
