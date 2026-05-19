"""Telegram adapter via aiogram>=3.

Inbound: aiogram's :class:`Dispatcher` routes Telegram updates to
:meth:`TelegramAdapter._on_message` (any message) and
:meth:`TelegramAdapter._on_callback` (inline-button clicks). Each
inbound message becomes a :class:`MessageEvent` and goes through
:meth:`GatewayAdapter.handle_inbound` — which means the base's
busy-session policy (merge-on-text, queue-on-photo, bypass-command
routing) lights up here for free.

Outbound: ``send_text`` posts to the chat with Markdown parse mode;
``send_file`` uploads as a document. Approval prompts render as a
two-button inline keyboard whose callback_data carries the request_id,
so :meth:`_on_callback` can route the click back into the daemon's
:class:`ApprovalRouter`.

Photo / document / voice / video attachments arriving inbound are
*downloaded eagerly* to a per-session cache directory so the agent's
tool layer can read them as local files — Telegram's media URLs
expire and are not signed for direct download from an arbitrary HTTP
client anyway.

The aiogram SDK is intentionally imported inside :meth:`start` rather
than at module load. That keeps a headless install (no ``gateway``
extra) from import-erroring just because ``athena`` is invoked
without ``athena gateway run``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..base import GatewayAdapter
from ..events import ApprovalRequest, MessageEvent, MessageType

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from aiogram.types import (
        CallbackQuery,
        InlineKeyboardMarkup,
        Message,
    )

    from ..daemon import GatewayDaemon

logger = logging.getLogger(__name__)


# Callback-data shape for approval buttons:
#   "approve:<request_id>:<allow|deny>"
# Telegram caps callback_data at 64 bytes; "approve:" + 16-hex-chars +
# ":allow" fits well inside that budget.
_CALLBACK_PREFIX = "approve"
_CALLBACK_SEPARATOR = ":"


class TelegramAdapter(GatewayAdapter):
    """Telegram bot exposure for the gateway.

    Construct one per bot token. The adapter starts a long-polling
    loop in :meth:`start` (kicked off as a background task by
    :class:`GatewayDaemon.start`). Shutdown stops polling and closes
    the underlying aiohttp session inside aiogram.
    """

    name: str = "telegram"

    def __init__(
        self,
        daemon: GatewayDaemon,
        *,
        bot_token: str,
        parse_mode: str = "Markdown",
        attachment_dir: Path | None = None,
    ) -> None:
        super().__init__(daemon)
        if not bot_token:
            raise ValueError("bot_token must be non-empty")
        self.bot_token = bot_token
        self.parse_mode = parse_mode
        # Cache for downloaded attachments. Subdirectories per chat
        # keep things tidy; falls back to the profile dir.
        self.attachment_dir = (
            attachment_dir
            if attachment_dir is not None
            else daemon.profile_dir / "gateway_attachments" / self.name
        )
        self._bot: Bot | None = None
        self._dp: Dispatcher | None = None
        self._polling_task: asyncio.Task | None = None

    # ---- lifecycle ----

    async def start(self) -> None:
        """Construct the aiogram Bot / Dispatcher, install the
        approval renderer on the daemon, and run polling until
        cancelled.

        Returns only when the polling loop exits (i.e. on cancel from
        :meth:`stop`). The daemon wraps this in a background task.
        """
        from aiogram import Bot, Dispatcher

        self._bot = Bot(self.bot_token)
        self._dp = Dispatcher()
        # aiogram 3 prefers decorator OR explicit register; we use
        # register() so the handler functions stay easy to call
        # directly from unit tests.
        self._dp.message.register(self._on_message)
        self._dp.callback_query.register(self._on_callback)

        self.daemon.approvals.register_platform_renderer(
            self.name,
            self._render_approval,
        )

        try:
            await self._dp.start_polling(self._bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] polling loop crashed", self.name)
            raise

    async def stop(self) -> None:
        """Stop polling and clean up the bot session."""
        self.daemon.approvals.register_platform_renderer(self.name, None)
        if self._dp is not None:
            try:
                await self._dp.stop_polling()
            except Exception:
                logger.debug("[%s] dp.stop_polling raised", self.name, exc_info=True)
        if self._bot is not None:
            try:
                await self._bot.session.close()
            except Exception:
                logger.debug("[%s] bot.session.close raised", self.name, exc_info=True)

    # ---- inbound ----

    async def _on_message(self, message: Message) -> None:
        try:
            event = await self._event_from_message(message)
        except Exception:
            logger.exception("[%s] failed to normalize inbound message", self.name)
            return
        await self.handle_inbound(event)

    async def _event_from_message(self, message: Message) -> MessageEvent:
        """Convert an aiogram :class:`Message` into a platform-neutral
        :class:`MessageEvent`.

        Pulls the chat / sender ids out as strings, classifies the
        message type (text / photo / audio / video / document /
        sticker), and downloads any attachments to
        :attr:`attachment_dir` so the agent can read them as local
        files. Captions are joined into ``text`` so the agent gets
        the photo's context without extra plumbing.
        """
        chat = message.chat
        sender = getattr(message, "from_user", None)
        chat_id = str(chat.id)
        user_id = str(sender.id) if sender is not None else ""

        text, message_type = self._classify(message)

        reply_to_id: str | None = None
        rt = getattr(message, "reply_to_message", None)
        if rt is not None and getattr(rt, "message_id", None) is not None:
            reply_to_id = str(rt.message_id)

        attachments = await self._download_attachments(message, chat_id)

        return MessageEvent(
            platform=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            message_type=message_type,
            attachments=attachments,
            is_dm=(getattr(chat, "type", "") == "private"),
            reply_to_message_id=reply_to_id,
            platform_message_id=str(message.message_id),
        )

    @staticmethod
    def _classify(message: Message) -> tuple[str, MessageType]:
        """Return ``(text, message_type)`` from a Telegram message.

        Captions are surfaced as ``text`` for photo / video /
        document / audio messages so the agent sees the user's
        commentary without an extra trip into ``message.caption``.
        """
        if getattr(message, "photo", None):
            return (message.caption or "", MessageType.PHOTO)
        if getattr(message, "video", None):
            return (message.caption or "", MessageType.VIDEO)
        if getattr(message, "voice", None) or getattr(message, "audio", None):
            return (message.caption or "", MessageType.AUDIO)
        if getattr(message, "document", None):
            return (message.caption or "", MessageType.DOCUMENT)
        if getattr(message, "sticker", None):
            sticker = message.sticker
            emoji = getattr(sticker, "emoji", "") or ""
            return (emoji, MessageType.STICKER)
        return (message.text or "", MessageType.TEXT)

    async def _download_attachments(
        self,
        message: Message,
        chat_id: str,
    ) -> list[Path]:
        """Eagerly download every file_id on ``message`` to disk.

        Returns absolute paths under ``self.attachment_dir/<chat_id>/``.
        Failures log a warning and skip that one attachment — the
        agent still gets the message text, just without the file.
        """
        targets = self._extract_file_ids(message)
        if not targets:
            return []
        if self._bot is None:  # pragma: no cover — start() not yet called
            return []
        chat_dir = self.attachment_dir / chat_id
        chat_dir.mkdir(parents=True, exist_ok=True)
        out: list[Path] = []
        for file_id, suggested_name in targets:
            try:
                file_obj = await self._bot.get_file(file_id)
                dest = chat_dir / (suggested_name or _basename_for(file_obj, file_id))
                await self._bot.download_file(file_obj.file_path, destination=str(dest))
                out.append(dest)
            except Exception:
                logger.warning(
                    "[%s] failed to download attachment %s",
                    self.name,
                    file_id,
                    exc_info=True,
                )
        return out

    @staticmethod
    def _extract_file_ids(message: Message) -> list[tuple[str, str | None]]:
        """Return list of ``(file_id, suggested_filename)`` from a
        Telegram message. Photos resolve to their largest size; videos
        / documents / voice / audio use their single file_id."""
        out: list[tuple[str, str | None]] = []
        photos = getattr(message, "photo", None)
        if photos:
            # Telegram sends multiple sizes; take the largest (last).
            biggest = photos[-1]
            out.append((biggest.file_id, f"photo-{biggest.file_unique_id}.jpg"))
        video = getattr(message, "video", None)
        if video is not None:
            out.append((video.file_id, getattr(video, "file_name", None)))
        audio = getattr(message, "audio", None)
        if audio is not None:
            out.append((audio.file_id, getattr(audio, "file_name", None)))
        voice = getattr(message, "voice", None)
        if voice is not None:
            out.append((voice.file_id, f"voice-{voice.file_unique_id}.ogg"))
        document = getattr(message, "document", None)
        if document is not None:
            out.append((document.file_id, getattr(document, "file_name", None)))
        return out

    # ---- approval rendering ----

    async def _render_approval(self, request: ApprovalRequest) -> None:
        """Send the approval prompt as a Telegram message with
        inline allow/deny buttons.

        The chat to send to is the most-recently-seen Telegram route
        for the request's session (``request.chat_id`` is preferred
        when set). If the session has no Telegram route the request
        gets silently dropped — the caller's auto-deny-on-no-renderer
        fallback in :class:`ApprovalRouter` already handles that path.
        """
        if self._bot is None:  # pragma: no cover — start() not yet called
            logger.warning(
                "[%s] approval render fired before bot init; dropping",
                self.name,
            )
            return
        chat_id = self._resolve_chat_id(request)
        if chat_id is None:
            logger.warning(
                "[%s] no telegram route for session %s; cannot render approval",
                self.name,
                request.session_id,
            )
            return
        markup = self._build_approval_keyboard(request.request_id)
        body = self._format_approval_body(request)
        try:
            await self._bot.send_message(
                chat_id,
                body,
                parse_mode=self.parse_mode,
                reply_markup=markup,
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
    def _build_approval_keyboard(request_id: str) -> InlineKeyboardMarkup:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        allow_data = _CALLBACK_SEPARATOR.join((_CALLBACK_PREFIX, request_id, "allow"))
        deny_data = _CALLBACK_SEPARATOR.join((_CALLBACK_PREFIX, request_id, "deny"))
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Allow", callback_data=allow_data),
                    InlineKeyboardButton(text="✖ Deny", callback_data=deny_data),
                ]
            ]
        )

    @staticmethod
    def _format_approval_body(request: ApprovalRequest) -> str:
        """Render the approval prompt as Markdown. Truncates long
        argument values so the message fits inside Telegram's 4096-
        char body cap."""
        head = f"⚠ Run `{request.tool_name}`?"
        if not request.tool_args:
            return head
        # Render args as a compact one-per-line block. Long values
        # are truncated with an ellipsis so a 50KB script body
        # doesn't blow past the message cap.
        max_value_len = 200
        lines = [head, "", "Arguments:"]
        for key, value in request.tool_args.items():
            repr_value = str(value).replace("`", "ˋ")
            if len(repr_value) > max_value_len:
                repr_value = repr_value[:max_value_len] + "…"
            lines.append(f"`{key}` = `{repr_value}`")
        return "\n".join(lines)

    async def _on_callback(self, callback: CallbackQuery) -> None:
        """Inline-button click → route into the approval router.

        Acks the callback at the end (Telegram requires this within
        15s or the button shows as "still spinning"). Unknown or
        already-resolved request ids ack without surfacing an error
        — the user already saw the original prompt resolve via the
        message edit one path back.
        """
        data = callback.data or ""
        try:
            parts = data.split(_CALLBACK_SEPARATOR, 2)
            if len(parts) == 3 and parts[0] == _CALLBACK_PREFIX:
                _, request_id, decision = parts
                if decision in {"allow", "deny"}:
                    self.daemon.approvals.resolve(request_id, decision)
        finally:
            try:
                await callback.answer()
            except Exception:
                logger.debug(
                    "[%s] callback.answer raised",
                    self.name,
                    exc_info=True,
                )

    # ---- outbound ----

    async def send_text(self, chat_id: str, text: str) -> str:
        if self._bot is None:
            raise RuntimeError("TelegramAdapter.send_text called before start()")
        msg = await self._bot.send_message(
            chat_id,
            text,
            parse_mode=self.parse_mode,
        )
        return str(msg.message_id)

    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        from aiogram.types import FSInputFile

        if self._bot is None:
            raise RuntimeError("TelegramAdapter.send_file called before start()")
        msg = await self._bot.send_document(
            chat_id,
            FSInputFile(str(file_path)),
            caption=caption,
        )
        return str(msg.message_id)

    async def show_typing(self, chat_id: str) -> None:
        """Send a one-shot ``typing`` chat action.

        Telegram shows the indicator for ~5 seconds per call; the
        Phase 10.8 heartbeat loop refreshes it every 4s while a tool
        call runs.
        """
        if self._bot is None:
            return
        try:
            await self._bot.send_chat_action(chat_id, "typing")
        except Exception:
            logger.debug(
                "[%s] send_chat_action raised",
                self.name,
                exc_info=True,
            )


def _basename_for(file_obj: Any, fallback_file_id: str) -> str:
    """Derive a filename for a downloaded attachment.

    Telegram's :class:`File` object carries ``file_path`` (server-side
    path); we strip to the basename. If absent, fall back to the
    file_id so we never write to a collision-prone name.
    """
    path = getattr(file_obj, "file_path", None) or fallback_file_id
    return path.rsplit("/", 1)[-1]
