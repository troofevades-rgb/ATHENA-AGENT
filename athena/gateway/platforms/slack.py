"""Slack adapter via slack-sdk Socket Mode.

Socket Mode keeps the daemon behind any NAT — Slack initiates a
websocket to *us*, no public HTTPS endpoint or webhook URL needed.
Two tokens drive it:

- ``bot_token`` (``xoxb-...``) for outbound calls (chat.postMessage,
  files.upload_v2, reactions.add, …).
- ``app_token`` (``xapp-...``) for the Socket Mode handshake.

The same shape as :mod:`.telegram`:

- ``start`` constructs the two clients, registers a single
  request_listener that fans out by ``req.type``, registers the
  platform-scoped approval renderer on the daemon, and connects.
- ``stop`` removes the renderer and disconnects.
- Inbound message events become :class:`MessageEvent`s and go
  through :meth:`GatewayAdapter.handle_inbound`.
- ``block_actions`` interactive payloads from approval buttons route
  back into ``daemon.approvals.resolve``.

Slack has no native typing indicator for bots; the prompt for this
phase calls for a "status message edit" pattern instead — Phase 10.8
wires that in when the heartbeat loop lights up. For now,
:meth:`show_typing` is a documented no-op.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..base import GatewayAdapter
from ..events import ApprovalRequest, MessageEvent, MessageType

if TYPE_CHECKING:
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.web.async_client import AsyncWebClient

    from ..daemon import GatewayDaemon

logger = logging.getLogger(__name__)


# action_id shape: "approve:<request_id>:<allow|deny>"
_ACTION_PREFIX = "approve"
_ACTION_SEPARATOR = ":"


class SlackAdapter(GatewayAdapter):
    """Slack workspace exposure for the gateway."""

    name: str = "slack"

    def __init__(
        self,
        daemon: GatewayDaemon,
        *,
        bot_token: str,
        app_token: str,
        attachment_dir: Path | None = None,
    ) -> None:
        super().__init__(daemon)
        if not bot_token or not bot_token.startswith("xoxb-"):
            raise ValueError("bot_token must be a Slack bot token (xoxb-...)")
        if not app_token or not app_token.startswith("xapp-"):
            raise ValueError("app_token must be a Slack app token (xapp-...)")
        self.bot_token = bot_token
        self.app_token = app_token
        self.attachment_dir = (
            attachment_dir
            if attachment_dir is not None
            else daemon.profile_dir / "gateway_attachments" / self.name
        )
        self._web: AsyncWebClient | None = None
        self._socket: SocketModeClient | None = None
        # Bot's own user id, populated at start() from auth.test, so
        # we can filter out messages we sent ourselves.
        self._bot_user_id: str | None = None

    # ---- lifecycle ----

    async def start(self) -> None:
        from slack_sdk.socket_mode.aiohttp import SocketModeClient
        from slack_sdk.web.async_client import AsyncWebClient

        self._web = AsyncWebClient(token=self.bot_token)
        self._socket = SocketModeClient(
            app_token=self.app_token,
            web_client=self._web,
        )
        self._socket.socket_mode_request_listeners.append(self._on_request)

        # Identify ourselves so message filtering can drop our own posts.
        try:
            auth = await self._web.auth_test()
            self._bot_user_id = auth.get("user_id")
        except Exception:
            logger.warning(
                "[%s] auth.test failed; bot-self filter disabled",
                self.name,
                exc_info=True,
            )

        self.daemon.approvals.register_platform_renderer(
            self.name,
            self._render_approval,
        )

        await self._socket.connect()
        # Socket Mode's connect() returns once connected; the listener
        # runs as long as the websocket stays open. Block here until
        # someone cancels us so the daemon's start-task semantics work.
        import asyncio

        await asyncio.Future()  # never completes; cancelled by stop()

    async def stop(self) -> None:
        self.daemon.approvals.register_platform_renderer(self.name, None)
        if self._socket is not None:
            try:
                await self._socket.disconnect()
            except Exception:
                logger.debug(
                    "[%s] socket.disconnect raised",
                    self.name,
                    exc_info=True,
                )
        if self._web is not None:
            try:
                # AsyncWebClient closes its underlying aiohttp session.
                close = getattr(self._web, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
            except Exception:
                logger.debug(
                    "[%s] web.close raised",
                    self.name,
                    exc_info=True,
                )

    # ---- request fan-out --------------------------------------------

    async def _on_request(
        self,
        client: SocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        """Single listener for every Socket Mode envelope.

        The first thing we do for every request is ack — Slack
        retries un-acked requests, which would multiply work and
        confuse the busy-session policy. After ack we route by
        ``req.type``.
        """
        await self._ack(client, req)

        try:
            if req.type == "events_api":
                await self._handle_event(req.payload)
            elif req.type == "interactive":
                await self._handle_interactive(req.payload)
            else:
                logger.debug(
                    "[%s] ignoring unknown request type: %s",
                    self.name,
                    req.type,
                )
        except Exception:
            logger.exception(
                "[%s] handler raised for %s request",
                self.name,
                req.type,
            )

    async def _ack(
        self,
        client: SocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        from slack_sdk.socket_mode.response import SocketModeResponse

        try:
            await client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id),
            )
        except Exception:
            logger.debug(
                "[%s] socket ack raised for envelope %s",
                self.name,
                getattr(req, "envelope_id", "?"),
                exc_info=True,
            )

    # ---- inbound message --------------------------------------------

    async def _handle_event(self, payload: dict[str, Any]) -> None:
        event = payload.get("event") or {}
        if not isinstance(event, dict):
            return
        if event.get("type") != "message":
            return
        if self._should_skip(event):
            return
        try:
            msg_event = await self._event_from_slack(event)
        except Exception:
            logger.exception(
                "[%s] failed to normalize event",
                self.name,
            )
            return
        await self.handle_inbound(msg_event)

    def _should_skip(self, event: dict[str, Any]) -> bool:
        """Drop bot-authored messages so the gateway doesn't talk to
        itself. Slack flags these with ``bot_id`` or
        ``subtype="bot_message"`` (sometimes both)."""
        if event.get("bot_id"):
            return True
        if event.get("subtype") == "bot_message":
            return True
        if self._bot_user_id is not None and event.get("user") == self._bot_user_id:
            return True
        return False

    async def _event_from_slack(
        self,
        event: dict[str, Any],
    ) -> MessageEvent:
        chat_id = str(event.get("channel") or "")
        user_id = str(event.get("user") or "")
        text = str(event.get("text") or "")
        message_id = str(event.get("ts") or "")
        channel_type = event.get("channel_type") or ""
        is_dm = channel_type == "im"
        reply_to = event.get("thread_ts")
        reply_to_id = str(reply_to) if reply_to and reply_to != event.get("ts") else None
        attachments, message_type = await self._classify_and_download(event, chat_id)
        return MessageEvent(
            platform=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            message_type=message_type,
            attachments=attachments,
            is_dm=is_dm,
            reply_to_message_id=reply_to_id,
            platform_message_id=message_id,
            raw={"channel_type": channel_type},
        )

    async def _classify_and_download(
        self,
        event: dict[str, Any],
        chat_id: str,
    ) -> tuple[list[Path], MessageType]:
        """Pick the message type and (eagerly) download attachments.

        Slack files arrive with a ``url_private_download`` that
        requires the bot token in the ``Authorization`` header — we
        hand-roll an httpx GET so we don't depend on a particular
        slack-sdk download helper version.
        """
        files = event.get("files") or []
        if not files:
            return [], MessageType.TEXT

        # Pick a representative type from the first file's mimetype.
        first_mime = (files[0].get("mimetype") or "").lower()
        if first_mime.startswith("image/"):
            message_type = MessageType.PHOTO
        elif first_mime.startswith("audio/"):
            message_type = MessageType.AUDIO
        elif first_mime.startswith("video/"):
            message_type = MessageType.VIDEO
        else:
            message_type = MessageType.DOCUMENT

        if self._web is None:  # pragma: no cover — start() not yet called
            return [], message_type

        chat_dir = self.attachment_dir / chat_id
        chat_dir.mkdir(parents=True, exist_ok=True)

        import httpx

        downloaded: list[Path] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for f in files:
                url = f.get("url_private_download") or f.get("url_private")
                if not url:
                    continue
                name = f.get("name") or f.get("id") or "slack-file"
                dest = chat_dir / name
                try:
                    resp = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {self.bot_token}"},
                    )
                    resp.raise_for_status()
                    dest.write_bytes(resp.content)
                    downloaded.append(dest)
                except Exception:
                    logger.warning(
                        "[%s] failed to download slack file %s",
                        self.name,
                        f.get("id"),
                        exc_info=True,
                    )

        return downloaded, message_type

    # ---- interactive (button click) ---------------------------------

    async def _handle_interactive(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "block_actions":
            return
        actions = payload.get("actions") or []
        for action in actions:
            action_id = action.get("action_id") or ""
            parts = action_id.split(_ACTION_SEPARATOR, 2)
            if len(parts) != 3 or parts[0] != _ACTION_PREFIX:
                continue
            _, request_id, decision = parts
            if decision not in {"allow", "deny"}:
                continue
            self.daemon.approvals.resolve(request_id, decision)

    # ---- approval rendering -----------------------------------------

    async def _render_approval(self, request: ApprovalRequest) -> None:
        if self._web is None:  # pragma: no cover
            logger.warning(
                "[%s] approval render fired before web init; dropping",
                self.name,
            )
            return
        chat_id = self._resolve_chat_id(request)
        if chat_id is None:
            logger.warning(
                "[%s] no slack route for session %s; cannot render approval",
                self.name,
                request.session_id,
            )
            return
        text, blocks = self._build_approval_blocks(request)
        try:
            await self._web.chat_postMessage(
                channel=chat_id,
                text=text,
                blocks=blocks,
            )
        except Exception:
            logger.exception(
                "[%s] failed to render approval %s",
                self.name,
                request.request_id,
            )

    def _resolve_chat_id(self, request: ApprovalRequest) -> str | None:
        if request.chat_id:
            return request.chat_id
        routes = self.daemon.router.list_routes(platform=self.name)
        matching = [r for r in routes if r.session_id == request.session_id]
        if not matching:
            return None
        return max(matching, key=lambda r: r.last_seen_at).chat_id

    @staticmethod
    def _build_approval_blocks(
        request: ApprovalRequest,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Render Block Kit blocks for the approval prompt.

        Returns ``(fallback_text, blocks)`` — ``fallback_text`` shows
        in mobile notifications and a11y readers that ignore blocks.
        """
        head = f"⚠ Run `{request.tool_name}`?"
        body_lines = [f"*{head}*"]
        if request.tool_args:
            body_lines.append("")
            body_lines.append("*Arguments:*")
            for key, value in request.tool_args.items():
                repr_value = str(value)
                if len(repr_value) > 200:
                    repr_value = repr_value[:200] + "…"
                # Slack mrkdwn uses backticks for code; escape any
                # user-supplied backticks so the formatting holds.
                repr_value = repr_value.replace("`", "ˋ")
                body_lines.append(f"• `{key}` = `{repr_value}`")
        allow_id = _ACTION_SEPARATOR.join(
            (_ACTION_PREFIX, request.request_id, "allow"),
        )
        deny_id = _ACTION_SEPARATOR.join(
            (_ACTION_PREFIX, request.request_id, "deny"),
        )
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(body_lines)},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": allow_id,
                        "text": {"type": "plain_text", "text": "Allow"},
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "action_id": deny_id,
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                    },
                ],
            },
        ]
        return head, blocks

    # ---- outbound ---------------------------------------------------

    async def send_text(self, chat_id: str, text: str) -> str:
        if self._web is None:
            raise RuntimeError("SlackAdapter.send_text called before start()")
        resp = await self._web.chat_postMessage(channel=chat_id, text=text)
        return str(resp.get("ts") or "")

    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        if self._web is None:
            raise RuntimeError("SlackAdapter.send_file called before start()")
        resp = await self._web.files_upload_v2(
            channel=chat_id,
            file=str(file_path),
            initial_comment=caption or "",
            filename=file_path.name,
        )
        # files.upload_v2 returns {"file": {"id": ..., "permalink": ...}}
        file_info = resp.get("file") or {}
        return str(file_info.get("id") or "")

    async def show_typing(self, chat_id: str) -> None:
        """No-op for Slack.

        Slack's API has no per-message typing indicator for bot users.
        Phase 10.8's heartbeat path will instead send a "status"
        message (``chat.postMessage`` with ``"agent is working…"``)
        and edit it to the final response when ready — the analog of
        Telegram's repeating typing call.
        """
        return None
