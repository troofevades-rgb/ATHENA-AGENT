"""Signal adapter via signal-cli-rest-api.

signal-cli-rest-api wraps signal-cli (a Java CLI for the Signal
protocol) behind a REST + SSE interface. Run it in Docker; expose
its port to the daemon; we consume the HTTP API. No new Python
dependency — :mod:`httpx` already ships with athena.

Inbound: long-poll ``/v1/receive/<account>`` (returns a JSON array
of envelopes), parse each into a :class:`MessageEvent`, dispatch
through :meth:`handle_inbound`. Reconnects on transport failure
with exponential backoff bounded at 30s.

Outbound: ``POST /v2/send`` with ``{number, recipients, message}``.

Approval: text-only (Signal doesn't support inline buttons). The
renderer sends a prompt and records the pending request keyed on
the sender's UUID; the next ``/allow`` or ``/deny`` from that user
resolves it.

Setup is documented under ``docs/guides/gateway-signal.md`` — the
short version: ``docker run -d -p 8080:8080 -v signal-cli-config:
/home/.local/share/signal-cli bbernhard/signal-cli-rest-api``,
then register or link the account number via the bridge's
``/v1/qrcodelink`` or ``/v1/register`` endpoints before pointing
athena at it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ..base import GatewayAdapter
from ..events import ApprovalRequest, MessageEvent, MessageType
from ._text_approval import TextApprovalState

if TYPE_CHECKING:
    from ..daemon import GatewayDaemon

logger = logging.getLogger(__name__)


_DEFAULT_RECEIVE_TIMEOUT = 30.0
_RECONNECT_BASE = 2.0
_RECONNECT_MAX = 30.0


class SignalAdapter(GatewayAdapter, TextApprovalState):
    name: str = "signal"

    def __init__(
        self,
        daemon: GatewayDaemon,
        *,
        rest_url: str,
        account_number: str,
        attachment_dir: Path | None = None,
    ) -> None:
        GatewayAdapter.__init__(self, daemon)
        TextApprovalState.__init__(self)
        if not rest_url:
            raise ValueError("rest_url must be non-empty")
        if not account_number:
            raise ValueError("account_number must be a registered Signal number")
        self.rest_url = rest_url.rstrip("/")
        self.account = account_number
        self.attachment_dir = (
            attachment_dir
            if attachment_dir is not None
            else daemon.profile_dir / "gateway_attachments" / self.name
        )
        self._client: httpx.AsyncClient | None = None
        self._stop = asyncio.Event()

    # ---- lifecycle ----

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(_DEFAULT_RECEIVE_TIMEOUT))
        self.daemon.approvals.register_platform_renderer(
            self.name,
            self._render_approval,
        )
        backoff = _RECONNECT_BASE
        while not self._stop.is_set():
            try:
                await self._poll_loop()
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

    async def _poll_loop(self) -> None:
        """Long-poll the receive endpoint. Each call returns an
        array of pending envelopes (empty if no traffic since the
        last poll)."""
        url = f"{self.rest_url}/v1/receive/{self.account}"
        assert self._client is not None
        while not self._stop.is_set():
            r = await self._client.get(url, params={"timeout": 30})
            r.raise_for_status()
            envelopes = r.json() if r.content else []
            if isinstance(envelopes, dict):
                # Some bridge versions wrap in {"envelopes": [...]}.
                envelopes = envelopes.get("envelopes") or []
            for envelope in envelopes:
                try:
                    event = await self._event_from_envelope(envelope)
                except Exception:
                    logger.exception(
                        "[%s] event normalization failed",
                        self.name,
                    )
                    continue
                if event is None:
                    continue
                await self._dispatch(event)

    async def stop(self) -> None:
        self._stop.set()
        self.daemon.approvals.register_platform_renderer(self.name, None)
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.debug(
                    "[%s] client.aclose raised",
                    self.name,
                    exc_info=True,
                )

    # ---- inbound ----

    async def _dispatch(self, event: MessageEvent) -> None:
        if self.try_resolve_approval(event.user_id, event.text):
            return
        await self.handle_inbound(event)

    async def _event_from_envelope(
        self,
        envelope: dict[str, Any],
    ) -> MessageEvent | None:
        """Parse a signal-cli-rest-api envelope into a MessageEvent.

        Returns None for non-message envelopes (typing indicators,
        receipts, sync messages, etc.) which we ignore.
        """
        outer = envelope.get("envelope") if "envelope" in envelope else envelope
        if not isinstance(outer, dict):
            return None
        data = outer.get("dataMessage") or {}
        if not isinstance(data, dict):
            return None
        body = data.get("message")
        # Empty-body messages with only attachments / reactions are common;
        # we still want to surface attachments to the agent.
        attachments_raw = data.get("attachments") or []
        if not body and not attachments_raw:
            return None

        source = outer.get("source") or ""
        user_id = outer.get("sourceUuid") or source
        # chat_id: in 1:1 Signal, the same as source. Group messages
        # carry groupInfo.groupId we'd need to route to.
        group = data.get("groupInfo") or {}
        if isinstance(group, dict) and group.get("groupId"):
            chat_id = str(group["groupId"])
            is_dm = False
        else:
            chat_id = source
            is_dm = True

        attachments, message_type = await self._download_attachments(
            attachments_raw,
            chat_id,
        )

        return MessageEvent(
            platform=self.name,
            chat_id=str(chat_id),
            user_id=str(user_id),
            text=str(body or ""),
            message_type=message_type,
            attachments=attachments,
            is_dm=is_dm,
            platform_message_id=str(data.get("timestamp") or outer.get("timestamp") or ""),
            raw={"signal_envelope": outer},
        )

    async def _download_attachments(
        self,
        attachments_raw: list[dict[str, Any]],
        chat_id: str,
    ) -> tuple[list[Path], MessageType]:
        if not attachments_raw or self._client is None:
            return [], MessageType.TEXT

        first_mime = (
            attachments_raw[0].get("contentType") or attachments_raw[0].get("contentType", "")
        ).lower()
        if first_mime.startswith("image/"):
            mt = MessageType.PHOTO
        elif first_mime.startswith("audio/"):
            mt = MessageType.AUDIO
        elif first_mime.startswith("video/"):
            mt = MessageType.VIDEO
        else:
            mt = MessageType.DOCUMENT

        chat_dir = self.attachment_dir / _sanitize_for_path(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        out: list[Path] = []
        for att in attachments_raw:
            att_id = att.get("id")
            if not att_id:
                continue
            name = att.get("filename") or att_id
            dest = chat_dir / _sanitize_for_path(name)
            try:
                r = await self._client.get(
                    f"{self.rest_url}/v1/attachments/{att_id}",
                )
                r.raise_for_status()
                dest.write_bytes(r.content)
                out.append(dest)
            except Exception:
                logger.warning(
                    "[%s] attachment %s download failed",
                    self.name,
                    att_id,
                    exc_info=True,
                )
        return out, mt

    # ---- approval rendering ----

    async def _render_approval(self, request: ApprovalRequest) -> None:
        if self._client is None:  # pragma: no cover
            return
        chat_id, user_id = self._resolve_chat_and_user(request)
        if chat_id is None:
            logger.warning(
                "[%s] no signal route for session %s; cannot render approval",
                self.name,
                request.session_id,
            )
            return
        body = self.format_text_approval_prompt(request)
        try:
            await self._send_message(chat_id, body)
        except Exception:
            logger.exception(
                "[%s] approval send failed for %s",
                self.name,
                request.request_id,
            )
            return
        if user_id:
            self.record_pending(user_id, request.request_id)

    def _resolve_chat_and_user(
        self,
        request: ApprovalRequest,
    ) -> tuple[str | None, str | None]:
        if request.chat_id:
            # We don't always know the per-user id from chat_id alone
            # in group chats, but in Signal 1:1 chats they're equal.
            return request.chat_id, request.chat_id
        routes = self.daemon.router.list_routes(platform=self.name)
        matching = [r for r in routes if r.session_id == request.session_id]
        if not matching:
            return None, None
        latest = max(matching, key=lambda r: r.last_seen_at)
        return latest.chat_id, latest.user_id

    # ---- outbound ----

    async def send_text(self, chat_id: str, text: str) -> str:
        return await self._send_message(chat_id, text)

    async def _send_message(self, chat_id: str, text: str) -> str:
        if self._client is None:
            raise RuntimeError("SignalAdapter.send_text called before start()")
        payload = {
            "number": self.account,
            "recipients": [chat_id],
            "message": text,
        }
        r = await self._client.post(
            f"{self.rest_url}/v2/send",
            json=payload,
        )
        r.raise_for_status()
        data: Any = r.json() if r.content else {}
        if isinstance(data, dict):
            return str(data.get("timestamp") or "")
        return ""

    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        if self._client is None:
            raise RuntimeError("SignalAdapter.send_file called before start()")
        # signal-cli-rest-api takes base64 attachments in the same POST.
        import base64

        data = base64.b64encode(file_path.read_bytes()).decode("ascii")
        payload = {
            "number": self.account,
            "recipients": [chat_id],
            "message": caption or "",
            "base64_attachments": [
                f"data:application/octet-stream;filename={file_path.name};base64,{data}"
            ],
        }
        r = await self._client.post(
            f"{self.rest_url}/v2/send",
            json=payload,
        )
        r.raise_for_status()
        out: Any = r.json() if r.content else {}
        if isinstance(out, dict):
            return str(out.get("timestamp") or "")
        return ""

    async def show_typing(self, chat_id: str) -> None:
        """Signal has typing indicators but signal-cli-rest-api
        exposes them inconsistently. We POST to the typing endpoint
        as best-effort; the Phase 10.8 heartbeat refreshes every 4s
        so a missing call doesn't matter much."""
        if self._client is None:
            return
        try:
            await self._client.put(
                f"{self.rest_url}/v1/typing-indicator/{self.account}",
                json={"recipient": chat_id},
            )
        except Exception:
            logger.debug(
                "[%s] typing-indicator raised",
                self.name,
                exc_info=True,
            )


def _sanitize_for_path(value: str) -> str:
    """Strip filesystem-unfriendly characters from chat / file names."""
    safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)
    return safe or "anon"
