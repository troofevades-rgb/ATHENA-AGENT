"""Email adapter via IMAP IDLE + SMTP.

Email is the workhorse fallback — it works anywhere, doesn't need a
bridge, and lets non-technical users reach the agent from any
mail client. Tradeoffs:

- No buttons. Approvals use the same ``/allow`` / ``/deny`` text
  reply contract as Signal / iMessage.
- No real-time without IMAP IDLE. We rely on it; servers that
  don't support IDLE will have minute-scale latency (we poll
  every 30s when IDLE fails).
- Threading via ``In-Reply-To`` + ``References`` headers; mail
  clients render the conversation as one thread when these are
  set correctly.
- HTML emails get flattened to text via BeautifulSoup; text/plain
  parts are preferred when both are present.

Deliberate scope cut: no MIME attachment forwarding on inbound.
Email attachments are notoriously varied (encoding, calendar
invites, signed/encrypted bodies) and the agent rarely needs them
to answer the message body. If a use case emerges later we can
revisit.

Setup is documented under ``docs/guides/gateway-email.md``: enable
IMAP on the mailbox (Gmail App Passwords / Fastmail / iCloud
Passwords / etc.), set imap_* and smtp_* credentials in
``[gateway.platforms.email]``, configure ``allowed_senders`` to
gate who can talk to the agent.
"""

from __future__ import annotations

import asyncio
import email
import email.utils
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosmtplib

from ..base import GatewayAdapter
from ..events import ApprovalRequest, MessageEvent, MessageType
from ._text_approval import TextApprovalState

if TYPE_CHECKING:
    import aioimaplib

    from ..daemon import GatewayDaemon

logger = logging.getLogger(__name__)


_RECONNECT_BASE = 5.0
_RECONNECT_MAX = 60.0
_IDLE_TIMEOUT = 600.0
_POLL_INTERVAL_FALLBACK = 30.0


class EmailAdapter(GatewayAdapter, TextApprovalState):
    name: str = "email"

    def __init__(
        self,
        daemon: GatewayDaemon,
        *,
        imap_host: str,
        imap_user: str,
        imap_password: str,
        smtp_host: str,
        smtp_user: str,
        smtp_password: str,
        from_address: str,
        imap_port: int = 993,
        smtp_port: int = 587,
        subject_prefix: str = "[athena] ",
        allowed_senders: list[str] | None = None,
    ) -> None:
        GatewayAdapter.__init__(self, daemon)
        TextApprovalState.__init__(self)
        if not imap_host or not imap_user or not imap_password:
            raise ValueError("imap_host / imap_user / imap_password required")
        if not smtp_host or not smtp_user or not smtp_password:
            raise ValueError("smtp_host / smtp_user / smtp_password required")
        if not from_address:
            raise ValueError("from_address required")
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.subject_prefix = subject_prefix
        # Allowlist of canonical sender addresses (lowercased, no
        # surrounding name). None ⇒ anyone can talk to the agent.
        self.allowed_senders: set[str] | None = (
            {_canonical_address(s) for s in allowed_senders}
            if allowed_senders is not None
            else None
        )
        self._stop = asyncio.Event()
        # Track the most recent inbound Message-ID per sender so
        # outbound replies thread correctly.
        self._last_message_id: dict[str, str] = {}

    # ---- lifecycle ----

    async def start(self) -> None:
        self.daemon.approvals.register_platform_renderer(
            self.name,
            self._render_approval,
        )
        backoff = _RECONNECT_BASE
        while not self._stop.is_set():
            try:
                await self._receive_loop()
                backoff = _RECONNECT_BASE
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "[%s] receive loop crashed; backoff %.1fs",
                    self.name,
                    backoff,
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, _RECONNECT_MAX)

    async def _receive_loop(self) -> None:
        """Connect → login → SELECT INBOX → IDLE → fetch.

        On IDLE-not-supported, falls back to polling every
        :data:`_POLL_INTERVAL_FALLBACK` seconds.
        """
        import aioimaplib

        client = aioimaplib.IMAP4_SSL(self.imap_host, port=self.imap_port)
        await client.wait_hello_from_server()
        await client.login(self.imap_user, self.imap_password)
        await client.select("INBOX")
        try:
            # Process anything already pending before we start IDLE.
            await self._fetch_and_emit_unseen(client)
            while not self._stop.is_set():
                supports_idle = self._client_supports_idle(client)
                if supports_idle:
                    try:
                        idle = await client.idle_start(timeout=_IDLE_TIMEOUT)
                        await client.wait_server_push()
                        client.idle_done()
                        await idle
                    except asyncio.TimeoutError:
                        # IDLE keepalive expired; just re-poll.
                        pass
                else:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(),
                            timeout=_POLL_INTERVAL_FALLBACK,
                        )
                    except asyncio.TimeoutError:
                        pass
                if self._stop.is_set():
                    break
                await self._fetch_and_emit_unseen(client)
        finally:
            try:
                await client.logout()
            except Exception:
                pass

    @staticmethod
    def _client_supports_idle(client: aioimaplib.IMAP4_SSL) -> bool:
        caps = getattr(client, "protocol", None)
        capabilities = getattr(caps, "capabilities", []) if caps is not None else []
        if not capabilities:
            return False
        upper = {str(c).upper() for c in capabilities}
        return "IDLE" in upper

    async def stop(self) -> None:
        self._stop.set()
        self.daemon.approvals.register_platform_renderer(self.name, None)

    # ---- inbound ----

    async def _fetch_and_emit_unseen(
        self,
        client: aioimaplib.IMAP4_SSL,
    ) -> None:
        try:
            _typ, data = await client.uid_search("UNSEEN")
        except Exception:
            logger.warning(
                "[%s] UID SEARCH UNSEEN failed",
                self.name,
                exc_info=True,
            )
            return
        uids_blob = b" ".join(data) if isinstance(data, list) else data
        if isinstance(uids_blob, bytes):
            uids = [u for u in uids_blob.split() if u]
        else:
            uids = []
        for uid in uids:
            try:
                _typ2, msg_data = await client.uid("FETCH", uid, "(RFC822)")
                raw = _extract_rfc822(msg_data)
                if not raw:
                    continue
                event = self._event_from_email(raw)
                if event is None:
                    continue
                await self._dispatch(event)
            except Exception:
                logger.exception(
                    "[%s] failed to handle UID %s",
                    self.name,
                    uid,
                )

    def _event_from_email(self, raw: bytes) -> MessageEvent | None:
        msg = email.message_from_bytes(raw)
        sender = _canonical_address(msg.get("From") or "")
        if not sender:
            return None
        if self.allowed_senders is not None and sender not in self.allowed_senders:
            logger.info(
                "[%s] dropping unallowed sender %r",
                self.name,
                sender,
            )
            return None
        subject = (msg.get("Subject") or "").strip()
        body = _extract_body(msg)
        if not body and not subject:
            return None
        message_id = (msg.get("Message-ID") or "").strip()
        if message_id:
            self._last_message_id[sender] = message_id
        # Drop our own subject_prefix so the agent doesn't see its
        # own prefix back. Most replies preserve "Re: " — we strip
        # leading "Re:" repetitions too.
        clean_subject = _strip_subject_prefix(subject, self.subject_prefix)
        # Compose the user-visible text. Mail-style "Subject: …
        # \n\nBody" is what the agent gets; the agent has been
        # trained on similar shapes for a long time.
        text = f"Subject: {clean_subject}\n\n{body}" if clean_subject else body
        return MessageEvent(
            platform=self.name,
            chat_id=sender,
            user_id=sender,
            text=text,
            message_type=MessageType.TEXT,
            is_dm=True,  # email is inherently 1:1 for our purposes
            platform_message_id=message_id,
            raw={"subject": clean_subject},
        )

    async def _dispatch(self, event: MessageEvent) -> None:
        # Single-token /allow|/deny in the BODY (after Subject:) is
        # the canonical approval reply shape. parse_approval_decision
        # already rejects multi-word inputs so a sentence containing
        # "allow" doesn't trip it.
        body = event.text
        if "\n\n" in body:
            body = body.split("\n\n", 1)[1]
        if self.try_resolve_approval(event.user_id, body):
            return
        await self.handle_inbound(event)

    # ---- approval rendering ----

    async def _render_approval(self, request: ApprovalRequest) -> None:
        recipient = self._resolve_recipient(request)
        if recipient is None:
            logger.warning(
                "[%s] no email route for session %s; cannot render approval",
                self.name,
                request.session_id,
            )
            return
        body = self.format_text_approval_prompt(request)
        try:
            await self._send_email(
                recipient,
                body,
                subject_suffix=f"approval — {request.tool_name}",
            )
        except Exception:
            logger.exception(
                "[%s] approval email failed for %s",
                self.name,
                request.request_id,
            )
            return
        self.record_pending(recipient, request.request_id)

    def _resolve_recipient(self, request: ApprovalRequest) -> str | None:
        if request.chat_id:
            return request.chat_id
        routes = self.daemon.router.list_routes(platform=self.name)
        matching = [r for r in routes if r.session_id == request.session_id]
        if not matching:
            return None
        return max(matching, key=lambda r: r.last_seen_at).chat_id

    # ---- outbound ----

    async def send_text(self, chat_id: str, text: str) -> str:
        return await self._send_email(chat_id, text)

    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        return await self._send_email(
            chat_id,
            caption or f"(attached: {file_path.name})",
            attachments=[file_path],
        )

    async def show_typing(self, chat_id: str) -> None:
        """Email has no typing indicator. No-op by design."""
        return None

    async def _send_email(
        self,
        recipient: str,
        body: str,
        *,
        subject_suffix: str = "agent response",
        attachments: list[Path] | None = None,
    ) -> str:
        """Build a MIME message, set threading headers, send via SMTP."""
        mime: MIMEText | MIMEMultipart
        if attachments:
            mime = MIMEMultipart()
            mime.attach(MIMEText(body, "plain", "utf-8"))
            for path in attachments:
                _attach_file(mime, path)
        else:
            mime = MIMEText(body, "plain", "utf-8")
        mime["From"] = self.from_address
        mime["To"] = recipient
        mime["Subject"] = self.subject_prefix + subject_suffix
        msg_id = email.utils.make_msgid(domain=_domain_of(self.from_address))
        mime["Message-ID"] = msg_id
        # Thread the reply to the most recent inbound from this address.
        prior = self._last_message_id.get(_canonical_address(recipient))
        if prior:
            mime["In-Reply-To"] = prior
            mime["References"] = prior

        async with aiosmtplib.SMTP(
            hostname=self.smtp_host,
            port=self.smtp_port,
            use_tls=self.smtp_port == 465,
            start_tls=self.smtp_port == 587,
        ) as smtp:
            await smtp.login(self.smtp_user, self.smtp_password)
            await smtp.send_message(mime)
        return msg_id


# ---- helpers (module-level for tests) ----------------------------------


_EMAIL_RE = re.compile(r"<([^>]+)>")


def _canonical_address(value: str) -> str:
    """Strip surrounding "Display Name <addr@host>" → "addr@host" and
    lowercase. Returns "" if nothing addr-like is in the value.

    parseaddr accepts unstructured strings too — ``"no-email-here"``
    parses as ``("", "no-email-here")`` — so we additionally require
    the result to contain ``@`` before treating it as an address.
    Anything else is dropped to ``""``.
    """
    if not value:
        return ""
    _name, addr = email.utils.parseaddr(value)
    candidate = (addr or "").strip().lower()
    if "@" not in candidate:
        return ""
    return candidate


def _strip_subject_prefix(subject: str, prefix: str) -> str:
    """Drop our own ``[athena]`` prefix and any number of leading
    ``Re: `` markers from a Subject."""
    s = subject
    # Remove our prefix wherever it appears (some clients prepend
    # "Re: " then the prefix).
    if prefix and prefix in s:
        s = s.replace(prefix, "").strip()
    while s.lower().startswith("re:"):
        s = s[3:].lstrip()
    return s


def _extract_body(msg: email.message.Message) -> str:
    """Pick a text body from a possibly-multipart message.

    Order of preference:
    1. text/plain part (any nested multipart)
    2. text/html part flattened via BeautifulSoup
    3. fallback to ``get_payload(decode=True)`` if neither is found
    """
    plain: str | None = None
    html: str | None = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").lower().startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                continue
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except (LookupError, AttributeError):
                text = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain" and plain is None:
                plain = text
            elif ctype == "text/html" and html is None:
                html = text
    else:
        ctype = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
        except Exception:
            payload = None
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except (LookupError, AttributeError):
                text = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain":
                plain = text
            elif ctype == "text/html":
                html = text
            else:
                plain = text

    if plain is not None:
        return plain.strip()
    if html is not None:
        return _html_to_text(html).strip()
    return ""


def _html_to_text(html: str) -> str:
    """Flatten HTML to plain text. BeautifulSoup with the html.parser
    backend (stdlib-only — no need for the lxml extra)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover — bs4 is in [gateway]
        return html
    soup = BeautifulSoup(html, "html.parser")
    # Drop script / style; they're noise.
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines.
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_rfc822(msg_data: Any) -> bytes | None:
    """aioimaplib's FETCH response is a tuple/list; the RFC822
    payload is whichever element is a bytes blob long enough to be
    a message."""
    if isinstance(msg_data, (bytes, bytearray)):
        return bytes(msg_data)
    if not isinstance(msg_data, (list, tuple)):
        return None
    # Walk nested structure looking for the first bytes blob.
    stack: list[Any] = list(msg_data)
    while stack:
        item = stack.pop(0)
        if isinstance(item, (bytes, bytearray)) and len(item) > 50:
            return bytes(item)
        if isinstance(item, (list, tuple)):
            stack.extend(item)
    return None


def _attach_file(mime: MIMEMultipart, path: Path) -> None:
    """Attach ``path`` as an octet-stream MIME part. Used by
    send_file for arbitrary uploads."""
    from email.mime.application import MIMEApplication

    part = MIMEApplication(path.read_bytes(), Name=path.name)
    part["Content-Disposition"] = f'attachment; filename="{path.name}"'
    mime.attach(part)


def _domain_of(address: str) -> str:
    """Best-effort domain extraction for ``make_msgid``. Falls back
    to ``"athena.local"`` so the generated Message-ID is well-formed
    even if the from_address is malformed."""
    if "@" in address:
        return address.rsplit("@", 1)[1] or "athena.local"
    return "athena.local"
