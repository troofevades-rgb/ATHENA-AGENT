"""SignalAdapter — signal-cli-rest-api HTTP integration."""
from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from athena.gateway.events import ApprovalRequest, MessageEvent, MessageType
from athena.gateway.platforms._text_approval import parse_approval_decision
from athena.gateway.platforms.signal import SignalAdapter


class _FakeRouter:
    def __init__(self) -> None:
        self.calls = []
        self.routes = []

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


REST_URL = "http://signal-test"
ACCOUNT = "+15551234567"


def _adapter(tmp_path: Path) -> SignalAdapter:
    return SignalAdapter(
        _FakeDaemon(tmp_path),
        rest_url=REST_URL,
        account_number=ACCOUNT,
    )


# ---- constructor ----------------------------------------------------


def test_construct_requires_rest_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SignalAdapter(_FakeDaemon(tmp_path), rest_url="", account_number=ACCOUNT)


def test_construct_requires_account(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SignalAdapter(
            _FakeDaemon(tmp_path), rest_url=REST_URL, account_number="",
        )


def test_name_is_signal(tmp_path: Path) -> None:
    assert _adapter(tmp_path).name == "signal"


def test_strips_trailing_slash_from_rest_url(tmp_path: Path) -> None:
    a = SignalAdapter(
        _FakeDaemon(tmp_path),
        rest_url="http://signal-test/",
        account_number=ACCOUNT,
    )
    assert a.rest_url == "http://signal-test"


# ---- envelope parsing -----------------------------------------------


async def test_dm_envelope_parsed(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    envelope = {
        "envelope": {
            "source": "+15559999999",
            "sourceUuid": "abc-uuid",
            "sourceName": "Bob",
            "timestamp": 1700000000000,
            "dataMessage": {
                "timestamp": 1700000000000,
                "message": "hello",
            },
        }
    }
    event = await a._event_from_envelope(envelope)
    assert event is not None
    assert event.platform == "signal"
    assert event.chat_id == "+15559999999"
    assert event.user_id == "abc-uuid"
    assert event.text == "hello"
    assert event.is_dm is True
    assert event.message_type == MessageType.TEXT


async def test_group_envelope_marked_not_dm(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    envelope = {
        "envelope": {
            "source": "+15559999999",
            "sourceUuid": "u",
            "timestamp": 1,
            "dataMessage": {
                "timestamp": 1,
                "message": "hi room",
                "groupInfo": {"groupId": "group-base64-blob"},
            },
        }
    }
    event = await a._event_from_envelope(envelope)
    assert event.is_dm is False
    assert event.chat_id == "group-base64-blob"


async def test_non_data_envelope_returns_none(tmp_path: Path) -> None:
    """Receipts / typing notifications / sync events have no
    dataMessage; the adapter ignores them."""
    a = _adapter(tmp_path)
    envelope = {
        "envelope": {
            "source": "+1", "timestamp": 0,
            "receiptMessage": {"type": "READ"},
        }
    }
    assert await a._event_from_envelope(envelope) is None


async def test_empty_envelope_returns_none(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert await a._event_from_envelope({}) is None
    assert await a._event_from_envelope({"envelope": None}) is None


async def test_attachment_image_classified_and_downloaded(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a._client = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=REST_URL) as mock:
            mock.get("/v1/attachments/att-1").mock(
                return_value=httpx.Response(200, content=b"JPEGBYTES")
            )
            envelope = {
                "envelope": {
                    "source": "+1", "sourceUuid": "u", "timestamp": 1,
                    "dataMessage": {
                        "timestamp": 1, "message": "look",
                        "attachments": [{
                            "id": "att-1", "contentType": "image/jpeg",
                            "filename": "pic.jpg",
                        }],
                    },
                }
            }
            event = await a._event_from_envelope(envelope)
    finally:
        await a._client.aclose()

    assert event.message_type == MessageType.PHOTO
    assert len(event.attachments) == 1
    assert event.attachments[0].read_bytes() == b"JPEGBYTES"
    assert event.attachments[0].name == "pic.jpg"


async def test_attachment_download_failure_falls_through(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a._client = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=REST_URL) as mock:
            mock.get("/v1/attachments/att-x").mock(
                return_value=httpx.Response(403)
            )
            envelope = {
                "envelope": {
                    "source": "+1", "sourceUuid": "u", "timestamp": 1,
                    "dataMessage": {
                        "timestamp": 1, "message": "broken",
                        "attachments": [{
                            "id": "att-x", "contentType": "image/jpeg",
                        }],
                    },
                }
            }
            event = await a._event_from_envelope(envelope)
    finally:
        await a._client.aclose()

    # Type still inferred from the mimetype; just no file landed.
    assert event.message_type == MessageType.PHOTO
    assert event.attachments == []


# ---- approval intercept ---------------------------------------------


async def test_dispatch_intercepts_pending_approval(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    # Pretend we previously sent an approval prompt to user u-1.
    a.record_pending("u-1", "rid-1")

    await a._dispatch(MessageEvent(
        platform="signal", chat_id="c", user_id="u-1", text="/allow",
    ))
    a.handle_inbound.assert_not_awaited()
    assert a.daemon.approvals.resolves == [("rid-1", "allow")]


async def test_dispatch_with_no_pending_routes_normally(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._dispatch(MessageEvent(
        platform="signal", chat_id="c", user_id="u", text="/allow",
    ))
    # No pending mapping → falls through (the slash command will be
    # caught by base.handle_inbound's bypass logic if applicable).
    a.handle_inbound.assert_awaited_once()


async def test_dispatch_ignores_non_approval_text_with_pending(
    tmp_path: Path,
) -> None:
    """A pending approval doesn't trap normal conversation. If the
    user types something other than /allow|/deny, the message routes
    through normally and the pending stays open until they answer."""
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a.record_pending("u-1", "rid-1")

    await a._dispatch(MessageEvent(
        platform="signal", chat_id="c", user_id="u-1", text="actually nevermind",
    ))
    a.handle_inbound.assert_awaited_once()
    assert a.daemon.approvals.resolves == []
    # Pending stays so the next /allow|/deny still resolves.
    assert "u-1" in a._pending_text_approvals


# ---- approval rendering ----------------------------------------------


async def test_render_approval_sends_text_and_records_pending(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.post = AsyncMock(return_value=MagicMock(
        raise_for_status=MagicMock(), content=b"{}", json=lambda: {"timestamp": "1"},
    ))
    a.daemon.router.routes = [
        SimpleNamespace(
            session_id="s1", chat_id="+15559999999", user_id="abc-uuid",
            platform="signal", last_seen_at=datetime.now(timezone.utc),
        )
    ]
    req = ApprovalRequest(
        session_id="s1", tool_name="Bash", tool_args={"cmd": "ls"},
        request_id="rid-7", platform="signal",
    )
    await a._render_approval(req)
    a._client.post.assert_awaited_once()
    # The pending mapping is recorded against the user_id, not the
    # chat_id, because in groups multiple users could see the prompt
    # but only the requester should be able to resolve.
    assert a._pending_text_approvals == {"abc-uuid": "rid-7"}


async def test_render_approval_drops_when_no_route(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = MagicMock()
    a._client.post = AsyncMock()
    req = ApprovalRequest(
        session_id="missing", tool_name="Bash", tool_args={},
        request_id="r", platform="signal",
    )
    await a._render_approval(req)
    a._client.post.assert_not_awaited()


# ---- outbound -------------------------------------------------------


async def test_send_text_calls_v2_send(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a._client = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=REST_URL) as mock:
            mock.post("/v2/send").mock(
                return_value=httpx.Response(
                    200, json={"timestamp": "1700000000000"},
                )
            )
            ts = await a.send_text("+15559999999", "hello")
            assert ts == "1700000000000"
            req = mock.calls.last.request
            body = httpx.Request("POST", "/", content=req.content)
            import json
            payload = json.loads(req.content)
            assert payload["number"] == ACCOUNT
            assert payload["recipients"] == ["+15559999999"]
            assert payload["message"] == "hello"
    finally:
        await a._client.aclose()


async def test_send_text_before_start_raises(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    with pytest.raises(RuntimeError):
        await a.send_text("+1", "hi")


async def test_send_file_base64_encodes(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    f = tmp_path / "test.bin"
    f.write_bytes(b"binary data")
    a._client = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=REST_URL) as mock:
            mock.post("/v2/send").mock(
                return_value=httpx.Response(200, json={"timestamp": "1"})
            )
            await a.send_file("+15559999999", f, caption="check this")
            req = mock.calls.last.request
            import json
            payload = json.loads(req.content)
            assert payload["message"] == "check this"
            assert "base64_attachments" in payload
            blob = payload["base64_attachments"][0]
            assert "filename=test.bin" in blob
            assert "base64," in blob
            encoded = blob.split("base64,", 1)[1]
            assert base64.b64decode(encoded) == b"binary data"
    finally:
        await a._client.aclose()


async def test_show_typing_is_best_effort(tmp_path: Path) -> None:
    """Even if the typing endpoint is missing or returns 4xx, the
    adapter must not raise — typing is cosmetic."""
    a = _adapter(tmp_path)
    a._client = httpx.AsyncClient(timeout=5.0)
    try:
        async with respx.mock(base_url=REST_URL) as mock:
            mock.put(f"/v1/typing-indicator/{ACCOUNT}").mock(
                return_value=httpx.Response(404)
            )
            await a.show_typing("+15559999999")  # no exception
    finally:
        await a._client.aclose()


# ---- text-approval parser ----------------------------------------


def test_parse_allow_aliases() -> None:
    for token in ("/allow", "allow", "✅", "yes", "y", "ok", "OK", "Yes"):
        assert parse_approval_decision(token) == "allow"


def test_parse_deny_aliases() -> None:
    for token in ("/deny", "deny", "✖", "no", "n", "stop"):
        assert parse_approval_decision(token) == "deny"


def test_parse_rejects_multi_word() -> None:
    """Ambiguous multi-word inputs route as conversation, not as
    approval responses."""
    assert parse_approval_decision("yes please run it") is None
    assert parse_approval_decision("ok do it") is None


def test_parse_rejects_empty() -> None:
    assert parse_approval_decision("") is None
    assert parse_approval_decision("   ") is None


def test_parse_rejects_unknown_token() -> None:
    assert parse_approval_decision("maybe") is None
