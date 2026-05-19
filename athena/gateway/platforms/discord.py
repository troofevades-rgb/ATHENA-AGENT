"""Discord adapter via discord.py>=2.4.

Same shape as :mod:`.telegram` and :mod:`.slack`: ``start()`` connects
the SDK's :class:`discord.Client`, registers event handlers and the
platform-scoped approval renderer, then runs the gateway connection
until cancelled. ``stop()`` unregisters and closes the connection.

Inbound messages flow through :meth:`_on_message`. Approval prompts
render as a :class:`discord.ui.View` with two Button components whose
callbacks route directly into :meth:`GatewayDaemon.approvals.resolve`
(no callback_data parsing because discord.py wires buttons to bound
methods, not opaque strings).

Slash commands: ``/athena <prompt>`` is registered against the bot's
:class:`~discord.app_commands.CommandTree` and routed through the same
``handle_inbound`` pipeline so a slash-invoked turn lands on the same
session as the user's DM history.

Like the other adapters, the discord.py imports are inside
:meth:`start` so a headless install (no ``gateway`` extra) doesn't
import-error just because someone runs ``athena``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..base import GatewayAdapter
from ..events import ApprovalRequest, MessageEvent, MessageType

if TYPE_CHECKING:
    import discord

    from ..daemon import GatewayDaemon

logger = logging.getLogger(__name__)


class DiscordAdapter(GatewayAdapter):
    """Discord bot exposure for the gateway."""

    name: str = "discord"
    # Discord's hard limit on message content is 2000 chars; ``send``
    # 400's with error 50035 above that. 1900 leaves room for the
    # chunk-counter suffix ``_chunk_text`` may append, plus a markdown
    # code fence the model might split mid-block.
    body_cap: int = 1900

    def __init__(
        self,
        daemon: GatewayDaemon,
        *,
        bot_token: str,
        attachment_dir: Path | None = None,
    ) -> None:
        super().__init__(daemon)
        if not bot_token:
            raise ValueError("bot_token must be non-empty")
        self.bot_token = bot_token
        self.attachment_dir = (
            attachment_dir
            if attachment_dir is not None
            else daemon.profile_dir / "gateway_attachments" / self.name
        )
        self._client: discord.Client | None = None
        self._tree: Any = None  # discord.app_commands.CommandTree
        # Approval timeout for the ui.View; matches ApprovalRouter
        # default. Phase 10.8 will pass a tighter timeout when
        # per-request timeouts land.
        self.approval_view_timeout = 300.0

    # ---- lifecycle ----

    async def start(self) -> None:
        import discord
        from discord import app_commands

        intents = discord.Intents.default()
        intents.message_content = True  # required to read DM bodies
        self._client = discord.Client(intents=intents)
        self._tree = app_commands.CommandTree(self._client)

        # discord.py's base Client dispatches events via
        # ``getattr(self, 'on_<event>')``. The ``Client.event`` decorator
        # uses the handler's ``__name__`` to pick the attribute, which
        # silently misses for private-named methods like ``_on_message``
        # (gets registered as ``_on_message`` event — never fires).
        # ``add_listener`` is only on ``discord.ext.commands.Bot``, not
        # plain Client. Set the attribute directly: it's the same shape
        # ``Client.event`` would produce, just with the correct name.
        self._client.on_ready = self._on_ready  # type: ignore[method-assign]
        self._client.on_message = self._on_message  # type: ignore[method-assign]

        @self._tree.command(
            name="athena",
            description="Send a prompt to the athena agent.",
        )
        async def _athena_cmd(interaction: discord.Interaction, prompt: str) -> None:
            await self._on_slash_command(interaction, prompt)

        self.daemon.approvals.register_platform_renderer(
            self.name,
            self._render_approval,
        )

        await self._client.start(self.bot_token)

    async def _on_ready(self) -> None:
        """Discord's connection-ready event. Sync slash commands to
        the global command table so ``/athena`` becomes invocable.

        ``tree.sync()`` can take up to an hour to propagate globally
        on first run — Discord caches command lists aggressively.
        Subsequent runs with the same command set are no-ops.
        """
        if self._tree is None:
            return
        try:
            await self._tree.sync()
            logger.info(
                "[%s] connected as %s; slash commands synced",
                self.name,
                getattr(self._client, "user", "?"),
            )
        except Exception:
            logger.warning(
                "[%s] slash command sync failed",
                self.name,
                exc_info=True,
            )

    async def stop(self) -> None:
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

    # ---- inbound message ----

    async def _on_message(self, message: discord.Message) -> None:
        # Filter our own bot's posts so we don't talk to ourselves.
        if self._client is not None and message.author.id == getattr(
            getattr(self._client, "user", None),
            "id",
            None,
        ):
            return
        if getattr(message.author, "bot", False):
            # Skip other bots too — they generate noise and rarely
            # want a conversational reply.
            return
        try:
            event = await self._event_from_message(message)
        except Exception:
            logger.exception("[%s] event normalization failed", self.name)
            return
        await self.handle_inbound(event)

    async def _event_from_message(
        self,
        message: discord.Message,
    ) -> MessageEvent:
        import discord

        chat_id = str(message.channel.id)
        user_id = str(message.author.id)
        is_dm = isinstance(message.channel, discord.DMChannel)

        reply_to_id: str | None = None
        ref = getattr(message, "reference", None)
        if ref is not None and getattr(ref, "message_id", None) is not None:
            reply_to_id = str(ref.message_id)

        attachments, message_type, augmented_text = await self._classify_and_download(
            message,
            chat_id,
        )

        return MessageEvent(
            platform=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=augmented_text,
            message_type=message_type,
            attachments=attachments,
            is_dm=is_dm,
            reply_to_message_id=reply_to_id,
            platform_message_id=str(message.id),
        )

    async def _classify_and_download(
        self,
        message: discord.Message,
        chat_id: str,
    ) -> tuple[list[Path], MessageType, str]:
        """Classify the message by its first attachment's mime, then
        eagerly save every attachment to disk. Returns
        ``(paths, message_type, text)``.

        ``text`` is ``message.content``; we leave it untouched here.
        Per-attachment failures are skipped so a single broken
        download doesn't drop the whole turn.
        """
        text = message.content or ""
        attachments = list(getattr(message, "attachments", []) or [])
        if not attachments:
            return [], MessageType.TEXT, text

        first_mime = (getattr(attachments[0], "content_type", "") or "").lower()
        if first_mime.startswith("image/"):
            message_type = MessageType.PHOTO
        elif first_mime.startswith("audio/"):
            message_type = MessageType.AUDIO
        elif first_mime.startswith("video/"):
            message_type = MessageType.VIDEO
        else:
            message_type = MessageType.DOCUMENT

        chat_dir = self.attachment_dir / chat_id
        chat_dir.mkdir(parents=True, exist_ok=True)

        out: list[Path] = []
        for att in attachments:
            name = getattr(att, "filename", None) or str(getattr(att, "id", "discord-attachment"))
            dest = chat_dir / name
            try:
                save = getattr(att, "save", None)
                if save is None:
                    continue
                # discord.py's Attachment.save accepts a path or open
                # file. We pass the path so it owns the file handle.
                await save(str(dest))
                out.append(dest)
            except Exception:
                logger.warning(
                    "[%s] failed to save discord attachment %s",
                    self.name,
                    getattr(att, "id", "?"),
                    exc_info=True,
                )

        return out, message_type, text

    # ---- slash command ----

    async def _on_slash_command(
        self,
        interaction: discord.Interaction,
        prompt: str,
    ) -> None:
        """``/athena <prompt>``: feed the prompt through the same
        inbound pipeline as a regular message. Acknowledge the
        interaction immediately so Discord doesn't time it out.
        """
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            logger.debug(
                "[%s] slash defer failed",
                self.name,
                exc_info=True,
            )
        try:
            event = self._event_from_interaction(interaction, prompt)
        except Exception:
            logger.exception("[%s] slash event build failed", self.name)
            return
        await self.handle_inbound(event)

    def _event_from_interaction(
        self,
        interaction: discord.Interaction,
        prompt: str,
    ) -> MessageEvent:
        import discord

        channel = interaction.channel
        chat_id = str(channel.id) if channel is not None else ""
        user = interaction.user
        user_id = str(user.id) if user is not None else ""
        is_dm = isinstance(channel, discord.DMChannel) if channel else False
        return MessageEvent(
            platform=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=prompt,
            message_type=MessageType.TEXT,
            is_dm=is_dm,
            platform_message_id=str(interaction.id),
            raw={"via": "slash_command"},
        )

    # ---- approval rendering ----

    async def _render_approval(self, request: ApprovalRequest) -> None:
        if self._client is None:  # pragma: no cover
            logger.warning(
                "[%s] approval render fired before client init; dropping",
                self.name,
            )
            return
        chat_id = self._resolve_chat_id(request)
        if chat_id is None:
            logger.warning(
                "[%s] no discord route for session %s; cannot render approval",
                self.name,
                request.session_id,
            )
            return
        try:
            channel = await self._fetch_channel(chat_id)
        except Exception:
            logger.exception(
                "[%s] failed to fetch channel %s for approval",
                self.name,
                chat_id,
            )
            return
        if channel is None:
            return
        body = _format_approval_body(request)
        view = _build_approval_view(
            request.request_id,
            on_decision=self._on_approval_button,
            timeout=self.approval_view_timeout,
        )
        try:
            await channel.send(body, view=view)
        except Exception:
            logger.exception(
                "[%s] failed to send approval %s",
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

    async def _fetch_channel(self, chat_id: str) -> Any:
        """Resolve a chat_id (string-encoded int) to a discord channel.

        Tries the local cache first (``get_channel``), then a remote
        fetch (``fetch_channel``) — the former is fire-and-forget but
        only works for cached channels (those the bot has seen via an
        event); the latter is an API call but always works.
        """
        if self._client is None:
            return None
        try:
            cid = int(chat_id)
        except ValueError:
            return None
        cached = self._client.get_channel(cid)
        if cached is not None:
            return cached
        return await self._client.fetch_channel(cid)

    async def _on_approval_button(
        self,
        request_id: str,
        decision: str,
    ) -> None:
        if decision not in {"allow", "deny"}:
            return
        self.daemon.approvals.resolve(request_id, decision)

    # ---- outbound ----

    # Discord rejects content >2000 chars with HTTP 400 / 50035. The
    # gateway's _send_chunked is supposed to keep us under body_cap,
    # but a missed code path (slash-command replies, error messages,
    # future callers) shouldn't take down the whole reply. Defensive
    # truncation inside send_text guarantees the API call is always
    # well-formed: better a "(truncated)" tail than a 400.
    _DISCORD_HARD_LIMIT = 2000
    _DISCORD_TRUNC_SUFFIX = "\n…(truncated)"

    async def send_text(self, chat_id: str, text: str) -> str:
        channel = await self._fetch_channel(chat_id)
        if channel is None:
            raise RuntimeError(f"DiscordAdapter.send_text: no channel for chat_id={chat_id}")
        if len(text) > self._DISCORD_HARD_LIMIT:
            keep = self._DISCORD_HARD_LIMIT - len(self._DISCORD_TRUNC_SUFFIX)
            text = text[:keep] + self._DISCORD_TRUNC_SUFFIX
            logger.warning(
                "[%s] send_text truncated payload to %d chars for %s "
                "(caller bypassed body_cap chunking)",
                self.name,
                len(text),
                chat_id,
            )
        msg = await channel.send(text)
        return str(msg.id)

    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        import discord

        channel = await self._fetch_channel(chat_id)
        if channel is None:
            raise RuntimeError(f"DiscordAdapter.send_file: no channel for chat_id={chat_id}")
        msg = await channel.send(
            content=caption or None,
            file=discord.File(str(file_path)),
        )
        return str(msg.id)

    async def show_typing(self, chat_id: str) -> None:
        """One-shot typing indicator (Discord auto-expires after ~10s).

        Phase 10.8's heartbeat refreshes this every 8s for the
        duration of a tool call. Using ``channel.typing()`` as a
        brief context manager triggers exactly one ``send_typing``
        REST call.
        """
        channel = await self._fetch_channel(chat_id)
        if channel is None:
            return
        try:
            async with channel.typing():
                pass
        except Exception:
            logger.debug(
                "[%s] channel.typing raised",
                self.name,
                exc_info=True,
            )


# ---- helpers (module-level so tests can call directly) -----------------


def _format_approval_body(request: ApprovalRequest) -> str:
    r"""Render the approval prompt body.

    Truncates long argument values so the message fits inside
    Discord's 2000-char limit. Escapes triple-backticks so a user-
    supplied ``\`\`\`bash`` doesn't break the code-block fencing.
    """
    head = f"⚠ Run `{request.tool_name}`?"
    if not request.tool_args:
        return head

    lines = [head, "", "**Arguments:**"]
    for key, value in request.tool_args.items():
        repr_value = str(value).replace("```", "''' '''")
        if len(repr_value) > 200:
            repr_value = repr_value[:200] + "…"
        lines.append(f"`{key}` = `{repr_value}`")
    return "\n".join(lines)


def _build_approval_view(
    request_id: str,
    *,
    on_decision: Callable[[str, str], Any],
    timeout: float,
) -> discord.ui.View:
    """Construct a discord.ui.View with allow/deny buttons.

    ``on_decision(request_id, decision)`` is invoked from the button
    callback. The View times out after ``timeout`` seconds — the
    daemon's ApprovalRouter also enforces its own timeout, so the
    user sees an auto-deny either way.
    """
    from discord import ButtonStyle, ui

    class _ApprovalView(ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=timeout)
            self._request_id = request_id

        @ui.button(label="✅ Allow", style=ButtonStyle.success)
        async def allow_button(  # type: ignore[override]
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button,
        ) -> None:
            await self._resolve(interaction, "allow")

        @ui.button(label="✖ Deny", style=ButtonStyle.danger)
        async def deny_button(  # type: ignore[override]
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button,
        ) -> None:
            await self._resolve(interaction, "deny")

        async def _resolve(
            self,
            interaction: discord.Interaction,
            decision: str,
        ) -> None:
            result = on_decision(self._request_id, decision)
            if hasattr(result, "__await__"):
                await result
            try:
                await interaction.response.send_message(
                    f"Approval recorded: **{decision}**.",
                    ephemeral=True,
                )
            except Exception:
                logger.debug(
                    "approval interaction.response failed",
                    exc_info=True,
                )
            # Disable both buttons so the prompt can't be re-clicked.
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]
            self.stop()

    return _ApprovalView()
