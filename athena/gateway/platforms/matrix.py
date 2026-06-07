"""Matrix adapter via matrix-nio.

Matrix is the most feature-rich of the Phase 11 platforms: native
reactions for approval UI, end-to-end encryption support, federated
room model, and a real persistent client identity. matrix-nio is
the pure-Python client library — no native bridge required.

The adapter:

- Uses :func:`AsyncClient.sync_forever` for inbound (matrix-nio's
  recommended long-polling pattern). Event callbacks route to
  :meth:`_on_message` for room messages and :meth:`_on_reaction`
  for approval reactions.
- Uses ``room_send`` for outbound text and the upload/send dance
  for files. Reactions go through ``room_send`` too with
  ``m.reaction`` content type.
- Stores E2EE keys at ``<store_path>`` (defaults to
  ``<profile>/matrix_store/``) when matrix-nio's e2e extra is
  installed. Without it, only unencrypted rooms work.
- Renders approvals as a text message annotated with two reactions
  (✅ Allow / ✖ Deny) that the user can tap. The reaction handler
  resolves the pending request.

Setup is documented under ``docs/guides/gateway-matrix.md``: create
a bot account on your homeserver, get an access token (matrix.to /
Element under Settings → Help → Access Token), set the user_id and
device_id, point athena at it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..base import GatewayAdapter
from ..events import ApprovalRequest, MessageEvent, MessageType

if TYPE_CHECKING:
    from nio import AsyncClient, MatrixRoom, RoomMessageText

    from ..daemon import GatewayDaemon

logger = logging.getLogger(__name__)


_REACTION_ALLOW = "✅"
_REACTION_DENY = "✖"
_REACTION_CONTENT_KEY = "m.relates_to"


class MatrixAdapter(GatewayAdapter):
    name: str = "matrix"

    def __init__(
        self,
        daemon: GatewayDaemon,
        *,
        homeserver: str,
        user_id: str,
        access_token: str,
        device_id: str,
        store_path: Path | None = None,
        attachment_dir: Path | None = None,
    ) -> None:
        super().__init__(daemon)
        if not homeserver:
            raise ValueError("homeserver must be non-empty")
        if not user_id.startswith("@"):
            raise ValueError(f"user_id must be a Matrix MXID (@bot:server), got {user_id!r}")
        if not access_token:
            raise ValueError("access_token must be non-empty")
        if not device_id:
            raise ValueError("device_id must be non-empty")
        self.homeserver = homeserver.rstrip("/")
        self.user_id = user_id
        self.access_token = access_token
        self.device_id = device_id
        self.store_path = (
            store_path if store_path is not None else daemon.profile_dir / "matrix_store"
        )
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.attachment_dir = (
            attachment_dir
            if attachment_dir is not None
            else daemon.profile_dir / "gateway_attachments" / self.name
        )
        self._client: AsyncClient | None = None
        self._stop = asyncio.Event()
        # Per-request reaction tracking. When we render an approval
        # we send the prompt message + two reactions, then map
        # event_id_of_allow_reaction → request_id, etc. so when the
        # user taps a reaction (which generates an m.reaction event
        # referencing our reaction event_id) we know which request
        # they're voting on.
        #
        # NOTE: in the simple "send reactions ourselves" flow this
        # ends up tracking the reaction event_ids we just sent.
        # The simpler flow used in production: send the prompt
        # message, store prompt_event_id → request_id, and any
        # user-emitted m.reaction relating to that event with
        # key ✅ / ✖ resolves the request. We do the latter.
        self._prompt_to_request: dict[str, str] = {}

    # ---- lifecycle ----

    async def start(self) -> None:
        from nio import (
            AsyncClient,
            AsyncClientConfig,
            ReactionEvent,
            RoomMessageText,
        )

        config = AsyncClientConfig(
            max_limit_exceeded=0,
            max_timeouts=0,
            store_sync_tokens=True,
            encryption_enabled=_e2e_available(),
        )
        self._client = AsyncClient(
            self.homeserver,
            self.user_id,
            device_id=self.device_id,
            store_path=str(self.store_path) if config.encryption_enabled else None,
            config=config,
        )
        self._client.access_token = self.access_token
        # Tell nio we already know who we are so sync_forever doesn't
        # try to /login (we have an access_token, not a password).
        self._client.user_id = self.user_id
        self._client.device_id = self.device_id

        self._client.add_event_callback(self._on_message, RoomMessageText)
        self._client.add_event_callback(self._on_reaction, ReactionEvent)

        if config.encryption_enabled and self._client.should_upload_keys:
            try:
                await self._client.keys_upload()
            except Exception:
                logger.warning(
                    "[%s] keys_upload failed; E2EE rooms may not decrypt",
                    self.name,
                    exc_info=True,
                )

        self.daemon.approvals.register_platform_renderer(
            self.name,
            self._render_approval,
        )

        try:
            await self._client.sync_forever(
                timeout=30000,
                full_state=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] sync_forever crashed", self.name)
            raise

    async def stop(self) -> None:
        self._stop.set()
        self.daemon.approvals.register_platform_renderer(self.name, None)
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                logger.debug(
                    "[%s] client.close raised",
                    self.name,
                    exc_info=True,
                )

    # ---- inbound ----

    async def _on_message(
        self,
        room: MatrixRoom,
        event: RoomMessageText,
    ) -> None:
        # Skip our own echoes.
        if event.sender == self.user_id:
            return
        try:
            mev = self._event_from_room_message(room, event)
        except Exception:
            logger.exception(
                "[%s] _event_from_room_message raised",
                self.name,
            )
            return
        await self.handle_inbound(mev)

    def _event_from_room_message(
        self,
        room: MatrixRoom,
        event: RoomMessageText,
    ) -> MessageEvent:
        # DM detection: a Matrix DM is conventionally a room with
        # exactly 2 members (the user and the bot). Public rooms
        # don't qualify.
        users = getattr(room, "users", {}) or {}
        is_dm = len(users) == 2
        return MessageEvent(
            platform=self.name,
            chat_id=str(room.room_id),
            user_id=str(event.sender),
            text=str(event.body or ""),
            message_type=MessageType.TEXT,
            is_dm=is_dm,
            platform_message_id=str(event.event_id),
        )

    async def _on_reaction(
        self,
        room: MatrixRoom,
        event: Any,
    ) -> None:
        """User reacted to a previous event. If it was one of our
        approval prompts and the key is ✅ / ✖, resolve the request."""
        if event.sender == self.user_id:
            return
        try:
            relates = self._reaction_target(event)
            if relates is None:
                return
            target_event_id, key = relates
            request_id = self._prompt_to_request.get(target_event_id)
            if request_id is None:
                return
            decision: Literal["allow", "deny"]
            if key == _REACTION_ALLOW:
                decision = "allow"
            elif key == _REACTION_DENY:
                decision = "deny"
            else:
                return
            self._prompt_to_request.pop(target_event_id, None)
            self.daemon.approvals.resolve(request_id, decision)
        except Exception:
            logger.exception(
                "[%s] reaction handler raised",
                self.name,
            )

    @staticmethod
    def _reaction_target(event: Any) -> tuple[str, str] | None:
        """Extract (target_event_id, key) from a ReactionEvent.

        matrix-nio's ReactionEvent exposes ``key`` and the related
        event_id via either ``reacts_to`` or the raw content dict.
        We handle both shapes for compatibility across versions.
        """
        key = getattr(event, "key", None)
        target = getattr(event, "reacts_to", None)
        if not target:
            # Fallback to parsing the raw source.
            source = getattr(event, "source", None) or {}
            content = source.get("content") if isinstance(source, dict) else None
            relates = content.get(_REACTION_CONTENT_KEY) if isinstance(content, dict) else None
            if isinstance(relates, dict):
                target = relates.get("event_id")
                key = relates.get("key") or key
        if not target or not isinstance(key, str):
            return None
        return str(target), key

    # ---- approval rendering ----

    async def _render_approval(self, request: ApprovalRequest) -> None:
        if self._client is None:  # pragma: no cover
            return
        room_id = self._resolve_room_id(request)
        if room_id is None:
            logger.warning(
                "[%s] no matrix route for session %s; cannot render approval",
                self.name,
                request.session_id,
            )
            return
        body = _format_approval_body(request)
        try:
            resp = await self._client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": body},
            )
        except Exception:
            logger.exception(
                "[%s] approval prompt send failed for %s",
                self.name,
                request.request_id,
            )
            return
        prompt_event_id = getattr(resp, "event_id", None)
        if not prompt_event_id:
            return
        self._prompt_to_request[prompt_event_id] = request.request_id
        # Pre-seed our own ✅ / ✖ reactions so users get a clear
        # tap target. They tap one and we receive an m.reaction
        # event with their sender id.
        for key in (_REACTION_ALLOW, _REACTION_DENY):
            try:
                await self._client.room_send(
                    room_id=room_id,
                    message_type="m.reaction",
                    content={
                        _REACTION_CONTENT_KEY: {
                            "rel_type": "m.annotation",
                            "event_id": prompt_event_id,
                            "key": key,
                        }
                    },
                )
            except Exception:
                logger.debug(
                    "[%s] seed reaction send failed",
                    self.name,
                    exc_info=True,
                )

    def _resolve_room_id(self, request: ApprovalRequest) -> str | None:
        if request.chat_id:
            return request.chat_id
        routes = self.daemon.router.list_routes(platform=self.name)
        matching = [r for r in routes if r.session_id == request.session_id]
        if not matching:
            return None
        return max(matching, key=lambda r: r.last_seen_at).chat_id

    # ---- outbound ----

    async def send_text(self, chat_id: str, text: str) -> str:
        if self._client is None:
            raise RuntimeError("MatrixAdapter.send_text called before start()")
        resp = await self._client.room_send(
            room_id=chat_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": text},
        )
        return str(getattr(resp, "event_id", "") or "")

    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        if self._client is None:
            raise RuntimeError("MatrixAdapter.send_file called before start()")
        # Matrix upload+send dance: PUT the bytes to /upload, get an
        # mxc:// URI back, then room_send the URI as an m.file/m.image
        # event.
        import mimetypes

        mime, _ = mimetypes.guess_type(file_path.name)
        mime = mime or "application/octet-stream"

        with open(file_path, "rb") as fp:
            resp, _maybe_keys = await self._client.upload(
                lambda *_a, **_kw: fp,
                content_type=mime,
                filename=file_path.name,
                filesize=file_path.stat().st_size,
            )
        upload_uri = getattr(resp, "content_uri", None)
        if not upload_uri:
            raise RuntimeError(
                f"matrix upload returned no content_uri: {resp!r}",
            )

        msgtype = _msgtype_for_mime(mime)
        content: dict[str, Any] = {
            "msgtype": msgtype,
            "body": caption or file_path.name,
            "url": upload_uri,
            "info": {"mimetype": mime, "size": file_path.stat().st_size},
        }
        send_resp = await self._client.room_send(
            room_id=chat_id,
            message_type="m.room.message",
            content=content,
        )
        return str(getattr(send_resp, "event_id", "") or "")

    async def show_typing(self, chat_id: str) -> None:
        """Matrix has a first-class typing notification API. Send a
        4s typing window — the heartbeat loop will refresh."""
        if self._client is None:
            return
        try:
            await self._client.room_typing(chat_id, typing_state=True, timeout=4000)
        except Exception:
            logger.debug(
                "[%s] room_typing raised",
                self.name,
                exc_info=True,
            )


# ---- helpers (module-level for tests) ----------------------------------


def _format_approval_body(request: ApprovalRequest) -> str:
    """Markdown-flavored body. Matrix renders mrkdwn in most clients
    (Element, FluffyChat, etc.)."""
    head = f"⚠ Approve `{request.tool_name}`?"
    if not request.tool_args:
        return head + "\n\nTap ✅ to allow or ✖ to deny."
    lines = [head, "", "**Arguments:**"]
    for key, value in request.tool_args.items():
        repr_value = str(value)
        if len(repr_value) > 200:
            repr_value = repr_value[:200] + "…"
        repr_value = repr_value.replace("`", "ˋ")
        lines.append(f"- `{key}` = `{repr_value}`")
    lines.append("")
    lines.append("Tap ✅ to allow or ✖ to deny.")
    return "\n".join(lines)


def _msgtype_for_mime(mime: str) -> str:
    if mime.startswith("image/"):
        return "m.image"
    if mime.startswith("audio/"):
        return "m.audio"
    if mime.startswith("video/"):
        return "m.video"
    return "m.file"


def _e2e_available() -> bool:
    """Return True iff matrix-nio's E2EE extras are installed
    (libolm via python-olm). When False, E2EE rooms appear as
    encrypted blobs the adapter can't decrypt."""
    try:
        import olm  # noqa: F401

        return True
    except ImportError:
        return False
