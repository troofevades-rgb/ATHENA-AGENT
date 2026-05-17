"""IMessageAdapter — BlueBubbles bridge integration."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from athena.gateway.events import ApprovalRequest, MessageEvent, MessageType
from athena.gateway.platforms.imessage import IMessageAdapter


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


SERVER = "http://bluebubbles-test"
PASSWORD = "secret"


def _adapter(tmp_path: Path) -> IMessageAdapter:
    return IMessageAdapter(
        _FakeDaemon(tmp_path),
        server_url=SERVER,
        password=PASSWORD,
    )


# ---- constructor ----------------------------------------------------


def test_construct_requires_server_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        IMessageAdapter(_FakeDaemon(tmp_path), server_url="", password=PASSWORD)


def test_construct_requires_password(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        IMessageAdapter(_FakeDaemon(tmp_path), server_url=SERVER, password="")


def test_name_is_imessage(tmp_path: Path) -> None:
    assert _adapter(tmp_path).name == "imessage"


# ---- payload unwrap ------------------------------------------------


def test_unwrap_dict_data() -> None:
    payload = {"data": {"text": "hi", "chatGuid": "iMessage;-;+1"}}
    out = IMessageAdapter._unwrap_payload(payload)
    assert out == {"text": "hi", "chatGuid": "iMessage;-;+1"}


def test_unwrap_pre_unwrapped_dict() -> None:
    payload = {"text": "hi", "chatGuid": "x"}
    out = IMessageAdapter._unwrap_payload(payload)
    assert out == payload


def test_unwrap_json_string() -> None:
    out = IMessageAdapter._unwrap_payload('{"data": {"text": "hi"}}')
    assert out == {"text": "hi"}


def test_unwrap_malformed_returns_none() -> None:
    assert IMessageAdapter._unwrap_payload("not json") is None
    assert IMessageAdapter._unwrap_payload(42) is None
    assert IMessageAdapter._unwrap_payload(None) is None


# ---- _event_from_data ----------------------------------------------


async def test_dm_event_from_data(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_data({
        "guid": "MSG-1",
        "chatGuid": "iMessage;-;+15551234567",
        "text": "hi there",
        "isFromMe": False,
        "isGroup": False,
        "handle": {"address": "+15551234567"},
    })
    assert event is not None
    assert event.platform == "imessage"
    assert event.chat_id == "iMessage;-;+15551234567"
    assert event.user_id == "+15551234567"
    assert event.text == "hi there"
    assert event.is_dm is True
    assert event.platform_message_id == "MSG-1"


async def test_group_event_marked_not_dm(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    event = await a._event_from_data({
        "guid": "MSG-2",
        "chatGuid": "iMessage;+;chat0000abcd",
        "text": "hey all",
        "isFromMe": False,
        "isGroup": True,
        "handle": {"address": "alice@example.com"},
    })
    assert event.is_dm is False
    assert event.user_id == "alice@example.com"


async def test_chats_fallback_when_chat_guid_missing(tmp_path: Path) -> None:
    """Older BlueBubbles versions used a chats[] array."""
    a = _adapter(tmp_path)
    event = await a._event_from_data({
        "guid": "MSG-3",
        "text": "hi",
        "isFromMe": False,
        "handle": {"address": "+1"},
        "chats": [{"guid": "iMessage;-;+15551234567"}],
    })
    assert event.chat_id == "iMessage;-;+15551234567"


async def test_data_without_chat_returns_none(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    out = await a._event_from_data({
        "guid": "M", "text": "x", "isFromMe": False, "handle": {},
    })
    assert out is None


async def test_data_with_no_text_or_attachments_returns_none(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    out = await a._event_from_data({
        "guid": "M", "chatGuid": "C", "text": "", "isFromMe": False,
        "handle": {"address": "u"},
    })
    assert out is None


async def test_attachment_classified_and_downloaded(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._http = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=SERVER) as mock:
            mock.get("/api/v1/attachment/A-1/download").mock(
                return_value=httpx.Response(200, content=b"PNGBYTES")
            )
            event = await a._event_from_data({
                "guid": "M", "chatGuid": "C", "text": "see this",
                "isFromMe": False, "isGroup": False, "handle": {"address": "u"},
                "attachments": [{
                    "guid": "A-1", "mimeType": "image/png",
                    "transferName": "img.png",
                }],
            })
    finally:
        await a._http.aclose()
    assert event.message_type == MessageType.PHOTO
    assert len(event.attachments) == 1
    assert event.attachments[0].read_bytes() == b"PNGBYTES"


async def test_attachment_unknown_mime_classifies_document(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a._http = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=SERVER) as mock:
            mock.get("/api/v1/attachment/A-2/download").mock(
                return_value=httpx.Response(200, content=b"PDF")
            )
            event = await a._event_from_data({
                "guid": "M", "chatGuid": "C", "text": "",
                "isFromMe": False, "handle": {"address": "u"},
                "attachments": [{
                    "guid": "A-2", "mimeType": "application/pdf",
                    "transferName": "doc.pdf",
                }],
            })
    finally:
        await a._http.aclose()
    assert event.message_type == MessageType.DOCUMENT


# ---- _on_new_message -----------------------------------------------


async def test_on_new_message_dispatches(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._on_new_message({
        "data": {
            "guid": "M", "chatGuid": "C", "text": "hi",
            "isFromMe": False, "isGroup": False, "handle": {"address": "u"},
        }
    })
    a.handle_inbound.assert_awaited_once()


async def test_on_new_message_skips_self(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._on_new_message({
        "data": {"guid": "M", "chatGuid": "C", "text": "x",
                 "isFromMe": True, "handle": {}}
    })
    a.handle_inbound.assert_not_awaited()


async def test_on_new_message_swallows_exceptions(tmp_path: Path) -> None:
    a = _adapter(tmp_path)

    async def bad(_data):
        raise RuntimeError("boom")

    a._event_from_data = bad  # type: ignore[assignment]
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._on_new_message({"data": {"guid": "M"}})  # no raise
    a.handle_inbound.assert_not_awaited()


# ---- approval intercept --------------------------------------------


async def test_dispatch_intercepts_pending_allow(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a.record_pending("+1", "rid-1")
    await a._dispatch(MessageEvent(
        platform="imessage", chat_id="C", user_id="+1", text="/allow",
    ))
    a.handle_inbound.assert_not_awaited()
    assert a.daemon.approvals.resolves == [("rid-1", "allow")]


async def test_dispatch_falls_through_without_pending(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._dispatch(MessageEvent(
        platform="imessage", chat_id="C", user_id="+1", text="hi",
    ))
    a.handle_inbound.assert_awaited_once()


# ---- approval rendering -------------------------------------------


async def test_render_approval_sends_and_records(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    a = _adapter(tmp_path)
    a._http = MagicMock()
    a._http.post = AsyncMock(return_value=MagicMock(
        raise_for_status=MagicMock(),
        content=b'{"data": {"guid": "x"}}',
        json=lambda: {"data": {"guid": "x"}},
    ))
    a.daemon.router.routes = [
        SimpleNamespace(
            session_id="s1", chat_id="iMessage;-;+1", user_id="+15551234567",
            platform="imessage", last_seen_at=datetime.now(timezone.utc),
        )
    ]
    req = ApprovalRequest(
        session_id="s1", tool_name="Bash", tool_args={"cmd": "ls"},
        request_id="rid-x", platform="imessage",
    )
    await a._render_approval(req)
    a._http.post.assert_awaited_once()
    assert a._pending_text_approvals == {"+15551234567": "rid-x"}


async def test_render_approval_drops_without_route(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._http = MagicMock()
    a._http.post = AsyncMock()
    req = ApprovalRequest(
        session_id="missing", tool_name="X", tool_args={},
        request_id="r", platform="imessage",
    )
    await a._render_approval(req)
    a._http.post.assert_not_awaited()


# ---- outbound -----------------------------------------------------


async def test_send_text_calls_bluebubbles_api(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._http = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=SERVER) as mock:
            mock.post("/api/v1/message/text").mock(
                return_value=httpx.Response(
                    200, json={"data": {"guid": "OUT-1"}},
                )
            )
            out = await a.send_text("iMessage;-;+15551234567", "hello")
            assert out == "OUT-1"
            req = mock.calls.last.request
            assert "password=secret" in str(req.url)
            import json
            payload = json.loads(req.content)
            assert payload["chatGuid"] == "iMessage;-;+15551234567"
            assert payload["message"] == "hello"
    finally:
        await a._http.aclose()


async def test_send_text_before_start_raises(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    with pytest.raises(RuntimeError):
        await a.send_text("C", "hi")


async def test_send_file_multipart_upload(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    a._http = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=SERVER) as mock:
            mock.post("/api/v1/message/attachment").mock(
                return_value=httpx.Response(
                    200, json={"data": {"guid": "ATT-7"}},
                )
            )
            out = await a.send_file("iMessage;-;+1", f, caption="check this")
            assert out == "ATT-7"
    finally:
        await a._http.aclose()


async def test_show_typing_emits_when_connected(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    sio = MagicMock()
    sio.connected = True
    sio.emit = AsyncMock()
    a._sio = sio
    await a.show_typing("C")
    sio.emit.assert_awaited_once_with("start-typing", {"chatGuid": "C"})


async def test_show_typing_noop_when_disconnected(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    sio = MagicMock()
    sio.connected = False
    sio.emit = AsyncMock()
    a._sio = sio
    await a.show_typing("C")
    sio.emit.assert_not_awaited()
