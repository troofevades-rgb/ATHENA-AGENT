"""iMessage adapter via BlueBubbles Server.

BlueBubbles is a community-maintained macOS-host bridge that exposes
the Messages app as a REST + Socket.IO API. It needs:

- A Mac (Intel or Apple Silicon) running BlueBubbles Server.
- That Mac signed into iMessage with the destination Apple ID.
- The bridge's password and address (typically over a tunnel —
  Tailscale or Cloudflare Tunnel — since exposing iMessage to the
  open internet is a footgun).

The adapter:

- Connects to BlueBubbles' Socket.IO endpoint (``python-socketio`` —
  BlueBubbles speaks Socket.IO v4 / Engine.IO v4) for inbound events.
- POSTs to its REST API for outbound (``/api/v1/message/text``,
  ``/api/v1/message/attachment``).
- Uses the :class:`TextApprovalState` mixin since iMessage has no
  native inline-button UI; approvals prompt the user to reply
  ``/allow`` or ``/deny``.

Setup is documented under ``docs/guides/gateway-imessage.md``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ..base import GatewayAdapter
from ..events import ApprovalRequest, MessageEvent, MessageType
from ._text_approval import TextApprovalState

if TYPE_CHECKING:
    import socketio

    from ..daemon import GatewayDaemon

logger = logging.getLogger(__name__)


_RECONNECT_BASE = 2.0
_RECONNECT_MAX = 30.0


class IMessageAdapter(GatewayAdapter, TextApprovalState):
    name: str = "imessage"

    def __init__(
        self,
        daemon: GatewayDaemon,
        *,
        server_url: str,
        password: str,
        attachment_dir: Path | None = None,
    ) -> None:
        GatewayAdapter.__init__(self, daemon)
        TextApprovalState.__init__(self)
        if not server_url:
            raise ValueError("server_url must be non-empty")
        if not password:
            raise ValueError(
                "password must be the BlueBubbles bridge password",
            )
        self.server_url = server_url.rstrip("/")
        self.password = password
        self.attachment_dir = (
            attachment_dir
            if attachment_dir is not None
            else daemon.profile_dir / "gateway_attachments" / self.name
        )
        self._sio: socketio.AsyncClient | None = None
        self._http: httpx.AsyncClient | None = None
        self._stop = asyncio.Event()

    # ---- lifecycle ----

    async def start(self) -> None:
        import socketio

        self._http = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30))
        self.daemon.approvals.register_platform_renderer(
            self.name,
            self._render_approval,
        )

        backoff = _RECONNECT_BASE
        while not self._stop.is_set():
            self._sio = socketio.AsyncClient(reconnection=False)
            self._sio.on("new-message", self._on_new_message)
            self._sio.on("disconnect", self._on_disconnect)
            try:
                await self._sio.connect(
                    self.server_url,
                    auth={"password": self.password},
                    transports=["websocket"],
                )
                logger.info("[%s] connected to %s", self.name, self.server_url)
                backoff = _RECONNECT_BASE
                await self._sio.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "[%s] socket.io connection failed; backoff %.1fs",
                    self.name,
                    backoff,
                )
            finally:
                try:
                    await self._sio.disconnect()
                except Exception:
                    pass
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, _RECONNECT_MAX)

    async def _on_disconnect(self) -> None:
        logger.info("[%s] socket.io disconnected", self.name)

    async def stop(self) -> None:
        self._stop.set()
        self.daemon.approvals.register_platform_renderer(self.name, None)
        if self._sio is not None:
            try:
                await self._sio.disconnect()
            except Exception:
                pass
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                pass

    # ---- inbound ----

    async def _on_new_message(self, raw: Any) -> None:
        """BlueBubbles ``new-message`` event handler.

        Payload shape (abbreviated):

            {"data": {"guid": ..., "text": ...,
                      "chatGuid": ..., "chats": [{"guid": ...}],
                      "handle": {"address": ...},
                      "isFromMe": false,
                      "attachments": [...]}}

        We skip echoes (``isFromMe == true``) and synthesize a
        :class:`MessageEvent` for the rest.
        """
        try:
            data = self._unwrap_payload(raw)
            if data is None:
                return
            if data.get("isFromMe"):
                return
            event = await self._event_from_data(data)
            if event is None:
                return
            await self._dispatch(event)
        except Exception:
            logger.exception("[%s] new-message handler raised", self.name)

    @staticmethod
    def _unwrap_payload(raw: Any) -> dict[str, Any] | None:
        """BlueBubbles wraps events as ``{"data": {...}}`` but some
        proxies pre-unwrap. Accept either shape."""
        if isinstance(raw, dict):
            inner = raw.get("data")
            if isinstance(inner, dict):
                return inner
            return raw
        if isinstance(raw, str):
            try:
                obj = json.loads(raw)
                return obj.get("data") if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    async def _event_from_data(
        self,
        data: dict[str, Any],
    ) -> MessageEvent | None:
        text = data.get("text") or ""
        # chatGuid is the canonical chat identifier; handle is the
        # sender. In a 1:1 thread, they're effectively tied to one
        # person; in a group thread, chatGuid identifies the room.
        chat_guid = data.get("chatGuid")
        if not chat_guid:
            chats = data.get("chats") or []
            if isinstance(chats, list) and chats:
                first = chats[0]
                if isinstance(first, dict):
                    chat_guid = first.get("guid")
        if not chat_guid:
            return None

        handle = data.get("handle") or {}
        if isinstance(handle, dict):
            user_id = str(handle.get("address") or "")
        else:
            user_id = ""

        attachments_raw = data.get("attachments") or []
        attachments, message_type = await self._classify_and_download(
            attachments_raw,
            str(chat_guid),
        )

        if not text and not attachments:
            return None

        is_dm = bool(data.get("isGroup") is False) or "iMessage;-;" in str(chat_guid)
        return MessageEvent(
            platform=self.name,
            chat_id=str(chat_guid),
            user_id=user_id,
            text=text,
            message_type=message_type,
            attachments=attachments,
            is_dm=is_dm,
            platform_message_id=str(data.get("guid") or ""),
            raw={"bluebubbles": data},
        )

    async def _classify_and_download(
        self,
        attachments_raw: list[dict[str, Any]],
        chat_guid: str,
    ) -> tuple[list[Path], MessageType]:
        if not attachments_raw or self._http is None:
            return [], MessageType.TEXT
        first_mime = (attachments_raw[0].get("mimeType") or "").lower()
        if first_mime.startswith("image/"):
            mt = MessageType.PHOTO
        elif first_mime.startswith("audio/"):
            mt = MessageType.AUDIO
        elif first_mime.startswith("video/"):
            mt = MessageType.VIDEO
        else:
            mt = MessageType.DOCUMENT

        chat_dir = self.attachment_dir / _safe_name(chat_guid)
        chat_dir.mkdir(parents=True, exist_ok=True)
        out: list[Path] = []
        for att in attachments_raw:
            guid = att.get("guid")
            if not guid:
                continue
            name = att.get("transferName") or att.get("originalRosename") or guid
            dest = chat_dir / _safe_name(name)
            try:
                r = await self._http.get(
                    f"{self.server_url}/api/v1/attachment/{guid}/download",
                    params={"password": self.password},
                )
                r.raise_for_status()
                dest.write_bytes(r.content)
                out.append(dest)
            except Exception:
                logger.warning(
                    "[%s] attachment %s download failed",
                    self.name,
                    guid,
                    exc_info=True,
                )
        return out, mt

    async def _dispatch(self, event: MessageEvent) -> None:
        if self.try_resolve_approval(event.user_id, event.text):
            return
        await self.handle_inbound(event)

    # ---- approval rendering ----

    async def _render_approval(self, request: ApprovalRequest) -> None:
        chat_guid, user_id = self._resolve_chat_and_user(request)
        if chat_guid is None:
            logger.warning(
                "[%s] no iMessage route for session %s; cannot render approval",
                self.name,
                request.session_id,
            )
            return
        body = self.format_text_approval_prompt(request)
        try:
            await self._send_text(chat_guid, body)
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
            return request.chat_id, request.chat_id
        routes = self.daemon.router.list_routes(platform=self.name)
        matching = [r for r in routes if r.session_id == request.session_id]
        if not matching:
            return None, None
        latest = max(matching, key=lambda r: r.last_seen_at)
        return latest.chat_id, latest.user_id

    # ---- outbound ----

    async def send_text(self, chat_id: str, text: str) -> str:
        return await self._send_text(chat_id, text)

    async def _send_text(self, chat_guid: str, text: str) -> str:
        if self._http is None:
            raise RuntimeError("IMessageAdapter.send_text called before start()")
        r = await self._http.post(
            f"{self.server_url}/api/v1/message/text",
            params={"password": self.password},
            json={
                "chatGuid": chat_guid,
                "message": text,
                "method": "apple-script",
            },
        )
        r.raise_for_status()
        body: Any = r.json() if r.content else {}
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            return str(data.get("guid") or "")
        return ""

    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        if self._http is None:
            raise RuntimeError("IMessageAdapter.send_file called before start()")
        with open(file_path, "rb") as f:
            files = {"attachment": (file_path.name, f, "application/octet-stream")}
            data = {
                "chatGuid": chat_id,
                "name": file_path.name,
                "tempGuid": file_path.name,
            }
            if caption:
                data["message"] = caption
            r = await self._http.post(
                f"{self.server_url}/api/v1/message/attachment",
                params={"password": self.password},
                data=data,
                files=files,
            )
        r.raise_for_status()
        body: Any = r.json() if r.content else {}
        result = body.get("data") if isinstance(body, dict) else None
        if isinstance(result, dict):
            return str(result.get("guid") or "")
        return ""

    async def show_typing(self, chat_id: str) -> None:
        """BlueBubbles supports a typing indicator over Socket.IO
        (``start-typing`` / ``stop-typing`` emits). Best-effort
        because some BlueBubbles versions don't accept them from
        clients."""
        if self._sio is None or not self._sio.connected:
            return
        try:
            await self._sio.emit("start-typing", {"chatGuid": chat_id})
        except Exception:
            logger.debug(
                "[%s] start-typing emit raised",
                self.name,
                exc_info=True,
            )


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value) or "anon"
