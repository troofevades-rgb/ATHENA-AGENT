"""EmailAdapter — IMAP IDLE + SMTP integration.

aioimaplib / aiosmtplib are mocked; the testable surface is the
adapter's parsing + send-side behavior, which doesn't need a real
mail server.
"""
from __future__ import annotations

import email
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from athena.gateway.events import ApprovalRequest, MessageEvent, MessageType
from athena.gateway.platforms.email import (
    EmailAdapter,
    _canonical_address,
    _extract_body,
    _extract_rfc822,
    _html_to_text,
    _strip_subject_prefix,
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


def _adapter(
    tmp_path: Path,
    *,
    allowed_senders: list[str] | None = None,
) -> EmailAdapter:
    return EmailAdapter(
        _FakeDaemon(tmp_path),
        imap_host="imap.example.com", imap_user="bot@example.com",
        imap_password="pw",
        smtp_host="smtp.example.com", smtp_user="bot@example.com",
        smtp_password="pw",
        from_address="bot@example.com",
        allowed_senders=allowed_senders,
    )


# ---- constructor ----------------------------------------------------


def test_construct_requires_imap_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        EmailAdapter(
            _FakeDaemon(tmp_path),
            imap_host="", imap_user="x", imap_password="x",
            smtp_host="s", smtp_user="s", smtp_password="s",
            from_address="from@x",
        )


def test_construct_requires_smtp_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        EmailAdapter(
            _FakeDaemon(tmp_path),
            imap_host="i", imap_user="i", imap_password="i",
            smtp_host="", smtp_user="s", smtp_password="s",
            from_address="from@x",
        )


def test_construct_requires_from_address(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        EmailAdapter(
            _FakeDaemon(tmp_path),
            imap_host="i", imap_user="i", imap_password="i",
            smtp_host="s", smtp_user="s", smtp_password="s",
            from_address="",
        )


def test_name_is_email(tmp_path: Path) -> None:
    assert _adapter(tmp_path).name == "email"


def test_allowed_senders_canonicalized(tmp_path: Path) -> None:
    a = _adapter(tmp_path, allowed_senders=[
        "Alice <ALICE@example.com>",
        "bob@example.com",
    ])
    assert a.allowed_senders == {"alice@example.com", "bob@example.com"}


def test_no_allowlist_means_anyone(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert a.allowed_senders is None


# ---- canonicalization helpers ---------------------------------------


def test_canonical_address_strips_display_name() -> None:
    assert _canonical_address("Alice <alice@example.com>") == "alice@example.com"


def test_canonical_address_lowercases() -> None:
    assert _canonical_address("BOB@EXAMPLE.COM") == "bob@example.com"


def test_canonical_address_empty_input() -> None:
    assert _canonical_address("") == ""
    assert _canonical_address("no-email-here") == ""


def test_strip_subject_prefix_removes_our_prefix() -> None:
    assert _strip_subject_prefix("[athena] hello", "[athena] ") == "hello"


def test_strip_subject_prefix_collapses_repeated_re() -> None:
    assert _strip_subject_prefix("Re: Re: Re: hello", "[athena] ") == "hello"


def test_strip_subject_prefix_handles_combined() -> None:
    """A reply from a client that prepended "Re:" to our prefix."""
    assert _strip_subject_prefix("Re: [athena] agent response", "[athena] ") == "agent response"


# ---- body extraction -----------------------------------------------


def test_extract_body_plain_text() -> None:
    msg = email.message_from_string(
        "Subject: t\nContent-Type: text/plain\n\nhello there\n"
    )
    assert _extract_body(msg) == "hello there"


def test_extract_body_multipart_prefers_plain_over_html() -> None:
    raw = (
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/alternative; boundary="b"\n\n'
        "--b\nContent-Type: text/plain\n\nplain body\n"
        "--b\nContent-Type: text/html\n\n<p>html body</p>\n"
        "--b--\n"
    )
    msg = email.message_from_string(raw)
    assert _extract_body(msg) == "plain body"


def test_extract_body_html_only_flattened() -> None:
    raw = (
        "MIME-Version: 1.0\nContent-Type: text/html\n\n"
        "<html><body><p>Hello</p><p>World</p></body></html>\n"
    )
    msg = email.message_from_string(raw)
    out = _extract_body(msg)
    assert "Hello" in out and "World" in out
    assert "<p>" not in out


def test_extract_body_skips_attachments() -> None:
    raw = (
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="x"\n\n'
        "--x\nContent-Type: text/plain\n\nmain body\n"
        "--x\nContent-Type: application/pdf\nContent-Disposition: attachment; filename=a.pdf\n\n"
        "binary blob\n"
        "--x--\n"
    )
    msg = email.message_from_string(raw)
    assert _extract_body(msg).strip() == "main body"


def test_html_to_text_drops_scripts_and_styles() -> None:
    html = """
    <html><head><style>body{color:red}</style></head>
    <body><script>alert(1)</script><p>visible</p></body></html>
    """
    out = _html_to_text(html)
    assert "alert" not in out
    assert "color:red" not in out
    assert "visible" in out


# ---- _extract_rfc822 ----------------------------------------------


def test_extract_rfc822_from_flat_bytes() -> None:
    raw = b"From: a@b\nSubject: hi\n\nbody body body body body body body"
    assert _extract_rfc822(raw) == raw


def test_extract_rfc822_from_nested_list() -> None:
    blob = b"X" * 200
    msg_data = [("UID 1 (RFC822", blob), b")"]
    assert _extract_rfc822(msg_data) == blob


def test_extract_rfc822_returns_none_for_empty() -> None:
    assert _extract_rfc822([]) is None
    assert _extract_rfc822(None) is None


# ---- _event_from_email ----------------------------------------------


def test_event_from_plain_email(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    raw = (
        "From: Alice <alice@example.com>\n"
        "To: bot@example.com\n"
        "Subject: [athena] hello agent\n"
        "Message-ID: <abc@example.com>\n"
        "Content-Type: text/plain\n\n"
        "Hi, please look at this thing.\n"
    )
    event = a._event_from_email(raw.encode())
    assert event is not None
    assert event.platform == "email"
    assert event.chat_id == "alice@example.com"
    assert event.user_id == "alice@example.com"
    assert "Subject: hello agent" in event.text
    assert "look at this thing" in event.text
    assert event.platform_message_id == "<abc@example.com>"
    # Message-ID tracked for threading.
    assert a._last_message_id["alice@example.com"] == "<abc@example.com>"


def test_event_dropped_for_unallowed_sender(tmp_path: Path) -> None:
    a = _adapter(tmp_path, allowed_senders=["alice@example.com"])
    raw = (
        "From: Mallory <mallory@example.com>\n"
        "Subject: hi\n\nhello\n"
    )
    assert a._event_from_email(raw.encode()) is None


def test_event_allowed_when_in_allowlist(tmp_path: Path) -> None:
    a = _adapter(tmp_path, allowed_senders=["alice@example.com"])
    raw = (
        "From: ALICE@example.com\n"
        "Subject: hi\n\nhello\n"
    )
    assert a._event_from_email(raw.encode()) is not None


def test_event_no_sender_dropped(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert a._event_from_email(b"Subject: x\n\nbody") is None


def test_event_empty_body_and_subject_dropped(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    raw = "From: alice@example.com\n\n"
    assert a._event_from_email(raw.encode()) is None


# ---- _dispatch with approval intercept ------------------------------


async def test_dispatch_intercepts_approval_in_body(tmp_path: Path) -> None:
    """Approval reply has the /allow|/deny BELOW the Subject line.
    parse_approval_decision sees just the body, not the subject."""
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a.record_pending("alice@example.com", "rid-7")
    await a._dispatch(MessageEvent(
        platform="email", chat_id="alice@example.com",
        user_id="alice@example.com",
        text="Subject: Re: [athena] approval\n\n/allow",
    ))
    a.handle_inbound.assert_not_awaited()
    assert a.daemon.approvals.resolves == [("rid-7", "allow")]


async def test_dispatch_falls_through_without_pending(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    await a._dispatch(MessageEvent(
        platform="email", chat_id="alice@example.com",
        user_id="alice@example.com",
        text="Subject: hello\n\nlook at this please",
    ))
    a.handle_inbound.assert_awaited_once()


async def test_dispatch_ignores_multi_word_body_with_pending(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    a.handle_inbound = AsyncMock()  # type: ignore[method-assign]
    a.record_pending("alice@example.com", "rid-9")
    await a._dispatch(MessageEvent(
        platform="email", chat_id="alice@example.com",
        user_id="alice@example.com",
        text="Subject: re\n\nyes please go ahead",
    ))
    a.handle_inbound.assert_awaited_once()
    assert a.daemon.approvals.resolves == []
    assert "alice@example.com" in a._pending_text_approvals


# ---- send_text ----------------------------------------------------


async def test_send_text_constructs_threaded_reply(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    # Pre-populate a prior Message-ID for threading.
    a._last_message_id["alice@example.com"] = "<prior@example.com>"

    sent: list[Any] = []
    fake_smtp = MagicMock()
    fake_smtp.__aenter__ = AsyncMock(return_value=fake_smtp)
    fake_smtp.__aexit__ = AsyncMock(return_value=False)
    fake_smtp.login = AsyncMock()
    fake_smtp.send_message = AsyncMock(side_effect=lambda m: sent.append(m))

    with patch(
        "athena.gateway.platforms.email.aiosmtplib.SMTP",
        return_value=fake_smtp,
    ):
        msg_id = await a.send_text("alice@example.com", "hello reply")

    assert msg_id  # well-formed Message-ID
    assert len(sent) == 1
    mime = sent[0]
    assert mime["From"] == "bot@example.com"
    assert mime["To"] == "alice@example.com"
    assert mime["Subject"].startswith("[athena]")
    assert mime["In-Reply-To"] == "<prior@example.com>"
    assert mime["References"] == "<prior@example.com>"


async def test_send_text_no_prior_inbound_no_in_reply_to(
    tmp_path: Path,
) -> None:
    a = _adapter(tmp_path)
    sent: list[Any] = []
    fake_smtp = MagicMock()
    fake_smtp.__aenter__ = AsyncMock(return_value=fake_smtp)
    fake_smtp.__aexit__ = AsyncMock(return_value=False)
    fake_smtp.login = AsyncMock()
    fake_smtp.send_message = AsyncMock(side_effect=lambda m: sent.append(m))
    with patch(
        "athena.gateway.platforms.email.aiosmtplib.SMTP",
        return_value=fake_smtp,
    ):
        await a.send_text("new@example.com", "first contact")
    mime = sent[0]
    assert "In-Reply-To" not in mime
    assert "References" not in mime


async def test_send_file_attaches_path(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4\nhello\n")
    sent: list[Any] = []
    fake_smtp = MagicMock()
    fake_smtp.__aenter__ = AsyncMock(return_value=fake_smtp)
    fake_smtp.__aexit__ = AsyncMock(return_value=False)
    fake_smtp.login = AsyncMock()
    fake_smtp.send_message = AsyncMock(side_effect=lambda m: sent.append(m))
    with patch(
        "athena.gateway.platforms.email.aiosmtplib.SMTP",
        return_value=fake_smtp,
    ):
        await a.send_file("alice@example.com", f, caption="See attached")
    mime = sent[0]
    # MIMEMultipart with one body part + one attachment.
    parts = list(mime.walk())
    assert any(p.get_filename() == "report.pdf" for p in parts)


async def test_show_typing_is_noop(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    assert await a.show_typing("alice@example.com") is None


# ---- approval rendering --------------------------------------------


async def test_render_approval_sends_email_and_records(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    a = _adapter(tmp_path)
    sent: list[Any] = []
    fake_smtp = MagicMock()
    fake_smtp.__aenter__ = AsyncMock(return_value=fake_smtp)
    fake_smtp.__aexit__ = AsyncMock(return_value=False)
    fake_smtp.login = AsyncMock()
    fake_smtp.send_message = AsyncMock(side_effect=lambda m: sent.append(m))

    a.daemon.router.routes = [
        SimpleNamespace(
            session_id="s1", chat_id="alice@example.com",
            user_id="alice@example.com", platform="email",
            last_seen_at=datetime.now(timezone.utc),
        )
    ]
    req = ApprovalRequest(
        session_id="s1", tool_name="Bash", tool_args={"cmd": "ls"},
        request_id="rid-Q", platform="email",
    )
    with patch(
        "athena.gateway.platforms.email.aiosmtplib.SMTP",
        return_value=fake_smtp,
    ):
        await a._render_approval(req)
    assert len(sent) == 1
    assert a._pending_text_approvals == {"alice@example.com": "rid-Q"}


async def test_render_approval_no_route_skips(tmp_path: Path) -> None:
    a = _adapter(tmp_path)
    fake_smtp = MagicMock()
    fake_smtp.__aenter__ = AsyncMock(return_value=fake_smtp)
    fake_smtp.__aexit__ = AsyncMock(return_value=False)
    fake_smtp.send_message = AsyncMock()
    with patch(
        "athena.gateway.platforms.email.aiosmtplib.SMTP",
        return_value=fake_smtp,
    ):
        req = ApprovalRequest(
            session_id="missing", tool_name="X", tool_args={},
            request_id="r", platform="email",
        )
        await a._render_approval(req)
    fake_smtp.send_message.assert_not_awaited()
