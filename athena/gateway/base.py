"""GatewayAdapter ABC — the contract every platform implements.

This module is a faithful port of the reliability primitives in Hermes
Agent's ``gateway/platforms/base.py`` — the patterns there encode
issue-driven hardening (split-brain recovery from #11016, the
command-ordering fix from PR #4926, photo-burst special-casing, etc.)
that earlier drafts of athena's design doc simplified away. We do not
re-simplify them.

The core data structures, all keyed by ``session_id``:

- ``_active_sessions: dict[str, asyncio.Event]`` — the per-session
  *guard*. While an entry exists, that session has an in-flight turn.
  Setting the event signals the running task that an interrupt is
  pending (a follow-up message arrived).
- ``_session_tasks: dict[str, asyncio.Task]`` — the owner task
  per session, recorded *atomically* with the guard so stale-lock
  detection has a single source of truth.
- ``_pending_messages: dict[str, MessageEvent]`` — at most *one*
  follow-up event per session, accumulated via
  :func:`merge_pending_message_event` so rapid text follow-ups append
  instead of clobbering and a photo burst aggregates into one event.
- ``_background_tasks: set[asyncio.Task]`` — every spawned processing
  task, so adapter shutdown can cancel them.
- ``_expected_cancelled_tasks: set[asyncio.Task]`` — tasks whose
  ``CancelledError`` is *expected* (because we cancelled them
  deliberately for ``/stop``-style commands) so logs stay quiet.

Key behaviors:

1. **Race-free guard install.** :meth:`_start_session_processing`
   writes ``_active_sessions[key]`` synchronously *before*
   ``asyncio.create_task`` so a second message arriving while the
   event loop is still scheduling the first task cannot pass the busy
   check and spawn a duplicate.
2. **Stale = task done.** :meth:`_session_task_is_stale` checks
   ``owner_task.done()`` — not a heartbeat clock. The split-brain case
   (issue #11016 in Hermes) is "guard still present, owner task already
   exited"; an age-based heuristic would either fire spuriously or
   miss it entirely.
3. **Interrupt on text, queue on photo.** When the session is busy,
   text follow-ups merge into the pending slot AND set the guard event
   (the in-flight task polls it and exits early). Photo events merge
   without setting the event so an album burst doesn't keep
   restarting the agent.
4. **Bypass commands.** ``/stop``, ``/new``, ``/reset``, ``/approve``,
   ``/deny``, ``/status``, ``/restart`` skip the busy guard.
   ``/stop|/new|/reset`` go through a dedicated handoff that cancels
   the in-flight task *after* the command's response sends, preserving
   message ordering (Hermes PR #4926).

``_process_message_background`` — the per-message work loop — is a
stub (``NotImplementedError``) in this prompt. Prompt 10.8 implements
it once the agent pool, approval router, and streaming protocol exist.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..text_utils import strip_think_blocks
from .events import MessageEvent, MessageType

if TYPE_CHECKING:
    from .daemon import GatewayDaemon  # added in Prompt 10.2

logger = logging.getLogger(__name__)


# Cadence for the typing-heartbeat refresh loop. Telegram's typing
# indicator persists ~5s; Discord's ~10s. 4s gives a comfortable
# refresh window for both without spamming Slack's rate limiter.
_TYPING_REFRESH_SECONDS = 4.0

# Minimum gap between in-turn progress lines shipped to the chat. The
# first line of a turn always goes through immediately (so the user
# sees the agent picked up the work); subsequent tool-round lines are
# throttled to this cadence so a tool-heavy turn doesn't bury the
# channel or trip the platform's message rate limit.
_PROGRESS_MIN_INTERVAL_SECONDS = 8.0

# Upper bound on media files (video/image) auto-delivered into the chat
# per turn. A guard against a runaway tool loop spamming attachments;
# anything beyond this is logged and left on the server.
_MAX_MEDIA_ARTIFACTS_PER_TURN = 8

# Bounds on relaying gateway_relay tool results into the chat: the most
# results a single turn can post, and the per-result char ceiling before
# truncation. Keep the char cap below a couple of body-cap chunks so a
# big result is a short scroll, not a channel flood.
_MAX_TOOL_RELAYS_PER_TURN = 5
_TOOL_RELAY_CHAR_CAP = 3500

# Default chat-body cap when an adapter doesn't override.
# Sized below Telegram's 4096 hard cap with headroom for Markdown
# formatting (the parse-mode markers, code-fence delimiters, etc.).
# Adapters with tighter limits override via :attr:`body_cap`.
_DEFAULT_BODY_CAP = 3500


# Commands that bypass the active-session guard entirely. Without this,
# /stop or /approve typed while the agent is mid-turn either leak into
# the next prompt as user text (/stop, /new) or deadlock (/approve,
# /deny — the agent is blocked on Event.wait waiting for a decision
# the user just sent).
BYPASS_COMMANDS: frozenset[str] = frozenset(
    {
        "stop",
        "new",
        "reset",
        "approve",
        "deny",
        "status",
        "restart",
    }
)

# Of those, the ones that must also cancel the in-flight task. They go
# through _dispatch_active_session_command so the cancel happens AFTER
# the command's own response sends (Hermes PR #4926).
CANCELING_BYPASS_COMMANDS: frozenset[str] = frozenset({"stop", "new", "reset"})


def merge_pending_message_event(
    pending_messages: dict[str, MessageEvent],
    session_id: str,
    event: MessageEvent,
    *,
    merge_text: bool = True,
) -> None:
    """Store or merge a pending event for a session.

    Photo bursts/albums arrive as multiple near-simultaneous PHOTO
    events; this merges them into one queued event so the next turn
    sees the whole burst. With ``merge_text=True`` (the default), rapid
    TEXT follow-ups append into the pending slot's ``text`` instead of
    replacing it — otherwise three rapid messages "A", "B", "C" become
    just "C" by the time the agent picks up the pending event.

    Resolution rules, in order:

    1. No existing pending → store ``event``.
    2. Existing+incoming are both PHOTO → extend attachments, merge
       captions, keep PHOTO type.
    3. Either side has media → extend attachments, append text. If
       either is PHOTO, the merged event becomes PHOTO; otherwise keep
       the non-TEXT type if there is one.
    4. Both are TEXT and ``merge_text=True`` → append text with a
       newline separator.
    5. Fall through → replace.
    """
    existing = pending_messages.get(session_id)
    if existing is None:
        pending_messages[session_id] = event
        return

    existing_is_photo = existing.message_type == MessageType.PHOTO
    incoming_is_photo = event.message_type == MessageType.PHOTO
    existing_has_media = bool(existing.attachments)
    incoming_has_media = bool(event.attachments)

    if existing_is_photo and incoming_is_photo:
        existing.attachments.extend(event.attachments)
        if event.text:
            existing.text = _merge_caption(existing.text, event.text)
        return

    if existing_has_media or incoming_has_media:
        if incoming_has_media:
            existing.attachments.extend(event.attachments)
        if event.text:
            existing.text = (
                _merge_caption(existing.text, event.text) if existing.text else event.text
            )
        if existing_is_photo or incoming_is_photo:
            existing.message_type = MessageType.PHOTO
        elif existing.message_type == MessageType.TEXT and event.message_type != MessageType.TEXT:
            existing.message_type = event.message_type
        return

    if (
        merge_text
        and existing.message_type == MessageType.TEXT
        and event.message_type == MessageType.TEXT
    ):
        if event.text:
            existing.text = f"{existing.text}\n{event.text}" if existing.text else event.text
        return

    pending_messages[session_id] = event


def _merge_caption(existing: str, incoming: str) -> str:
    """Combine two photo captions into one. Newline-separated; skips
    empties; deduplicates an exact-match repeat (common when the same
    caption arrives on every photo in an album)."""
    e = (existing or "").strip()
    i = (incoming or "").strip()
    if not e:
        return i
    if not i or e == i:
        return e
    return f"{e}\n{i}"


# Optional hook a daemon can install to short-circuit busy-session
# handling (returns True if it handled the event, False to fall through
# to default merge-and-interrupt behavior).
BusySessionHandler = Callable[[MessageEvent, str], Awaitable[bool]]


class GatewayAdapter(ABC):
    """Platform adapter base class.

    Subclasses set :attr:`name` to a stable platform slug
    (``"telegram"``, ``"slack"``, ``"discord"``, ...) and implement the
    four abstract methods. The shared :meth:`handle_inbound` orchestrates
    routing, stale-lock heal, bypass-command dispatch, busy-session
    interrupt/merge, and task spawning.
    """

    name: str = ""

    def __init__(self, daemon: GatewayDaemon) -> None:
        self.daemon = daemon
        self._active_sessions: dict[str, asyncio.Event] = {}
        self._session_tasks: dict[str, asyncio.Task[Any]] = {}
        self._pending_messages: dict[str, MessageEvent] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._expected_cancelled_tasks: set[asyncio.Task[Any]] = set()
        self._busy_session_handler: BusySessionHandler | None = None

    # ---- platform protocol ----

    @abstractmethod
    async def start(self) -> None:
        """Start the platform connection (polling loop, websocket, ...)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the platform connection gracefully."""

    @abstractmethod
    async def send_text(self, chat_id: str, text: str) -> str:
        """Send ``text`` to ``chat_id``. Returns the platform message id."""

    @abstractmethod
    async def send_file(
        self,
        chat_id: str,
        file_path: Path,
        caption: str | None = None,
    ) -> str:
        """Send a file (with optional caption). Returns the message id."""

    # ---- shared orchestration ----

    def set_busy_session_handler(self, handler: BusySessionHandler | None) -> None:
        """Install (or clear) an override for busy-session handling. If
        the handler returns True, default merge-and-interrupt is
        skipped — useful for daemons that want a platform-specific
        busy ack first."""
        self._busy_session_handler = handler

    # ---- access control (0.3.0 hardening) ----

    def _platform_config(self) -> dict[str, Any]:
        """Return this adapter's slice of ``[gateway.platforms.<name>]``.

        Empty dict when nothing is configured -- callers must treat the
        result as ``{}`` for back-compat (an undeclared adapter is one
        that opts into every default).
        """
        cfg = getattr(self.daemon, "cfg", None)
        if cfg is None:
            return {}
        # daemon.cfg is the full Config object; GatewayConfig lives at
        # cfg.gateway and exposes ``platforms: dict[str, Any]``.
        gateway = getattr(cfg, "gateway", None)
        if gateway is None:
            return {}
        platforms = getattr(gateway, "platforms", None) or {}
        slice_ = platforms.get(self.name) or {}
        return slice_ if isinstance(slice_, dict) else {}

    def _allowed_user_ids(self) -> frozenset[str]:
        """``allowed_user_ids`` from this adapter's platform config.

        Empty / missing -> no user filter (back-compat). When the
        operator populates the list, every inbound event must carry a
        ``user_id`` that's in the set or the adapter refuses to route
        it. The list lives under ``[gateway.platforms.<name>]
        allowed_user_ids = ["12345", ...]`` -- as strings, since
        Discord / Telegram / Slack ids are all numeric-string-shaped.
        """
        raw = self._platform_config().get("allowed_user_ids") or []
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return frozenset()
        return frozenset(str(x) for x in raw)

    def _allowed_chat_ids(self) -> frozenset[str]:
        """``allowed_chat_ids`` from this adapter's platform config.
        Same semantics as :meth:`_allowed_user_ids` but keyed on
        ``MessageEvent.chat_id`` -- useful for confining a Discord bot
        to specific channels or a Telegram bot to specific group ids."""
        raw = self._platform_config().get("allowed_chat_ids") or []
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return frozenset()
        return frozenset(str(x) for x in raw)

    def _is_authorized(self, event: MessageEvent) -> bool:
        """Refuse-by-allowlist check applied at the top of
        :meth:`handle_inbound`. Empty allowlists -> always authorized
        (back-compat with the pre-0.3.0 open posture). When EITHER list
        is populated, the event must satisfy both filters that the
        operator set: a user-allowlist with a chat-allowlist requires
        BOTH to match; only one populated requires only that one."""
        user_ok = True
        chat_ok = True
        users = self._allowed_user_ids()
        if users:
            user_ok = str(event.user_id) in users
        chats = self._allowed_chat_ids()
        if chats:
            chat_ok = str(event.chat_id) in chats
        return user_ok and chat_ok

    async def handle_inbound(self, event: MessageEvent) -> None:
        """Process an inbound event, dispatching to the right policy.

        Returns quickly: when a new processing task is needed it is
        spawned via :meth:`_start_session_processing` and this method
        returns without awaiting it.
        """
        # 0.3.0 hardening: refuse any message from a user / channel not
        # in the operator's allowlist BEFORE we touch the router,
        # spawn a task, or even acknowledge the message. Default-empty
        # allowlists preserve the pre-0.3.0 open posture so existing
        # deployments don't break; populating either list at
        # ``[gateway.platforms.<name>]`` in config.toml turns the
        # check on. Logged at INFO so an operator can see drift in
        # ``athena gateway logs`` without enabling debug.
        if not self._is_authorized(event):
            logger.info(
                "[%s] rejected inbound message: user_id=%s chat_id=%s not in allowlist",
                self.name,
                event.user_id,
                event.chat_id,
            )
            return

        session_id = await self.daemon.router.resolve(event)

        # On-entry self-heal: if the adapter has a guard for this
        # session but the owner task already exited, clear it and fall
        # through to normal dispatch (Hermes issue #11016 split-brain).
        if session_id in self._active_sessions:
            self._heal_stale_session_lock(session_id)

        # Busy path: a live owner task is still running this session.
        if session_id in self._active_sessions:
            cmd = event.get_command()

            if cmd in BYPASS_COMMANDS:
                if cmd in CANCELING_BYPASS_COMMANDS:
                    await self._dispatch_active_session_command(event, session_id, cmd)
                else:
                    await self._dispatch_bypass_command(event, session_id, cmd)
                return

            if self._busy_session_handler is not None:
                try:
                    if await self._busy_session_handler(event, session_id):
                        return
                except Exception:
                    logger.exception(
                        "[%s] busy_session_handler raised; falling through",
                        self.name,
                    )

            # Photo bursts queue without interrupting — albums arrive as
            # several near-simultaneous events and re-interrupting the
            # agent on each one would thrash.
            if event.message_type == MessageType.PHOTO:
                logger.debug(
                    "[%s] queuing photo follow-up for %s without interrupt",
                    self.name,
                    session_id,
                )
                merge_pending_message_event(
                    self._pending_messages,
                    session_id,
                    event,
                    merge_text=False,
                )
                return

            # Default: merge and interrupt. The running task polls the
            # guard event and exits early; its cleanup drains pending.
            logger.debug(
                "[%s] new message while %s busy — triggering interrupt",
                self.name,
                session_id,
            )
            merge_pending_message_event(
                self._pending_messages,
                session_id,
                event,
                merge_text=True,
            )
            self._active_sessions[session_id].set()
            return

        # Free path: install the guard synchronously, then spawn.
        self._start_session_processing(event, session_id)

    # ---- guard / task lifecycle ----

    def _session_task_is_stale(self, session_id: str) -> bool:
        """Return True iff the recorded owner task for ``session_id``
        has exited. No recorded task → not stale (the guard was
        installed by some path other than handle_inbound, e.g. tests).
        """
        task = self._session_tasks.get(session_id)
        if task is None:
            return False
        done = getattr(task, "done", None)
        return bool(done and done())

    def _heal_stale_session_lock(self, session_id: str) -> bool:
        """Pop guard + owner-task + pending if the owner has exited.
        Returns True iff a heal occurred. The fix from issue #11016 —
        without it, an exception inside a processing task that bypassed
        the normal cleanup leaves the session trapped behind a guard
        that nothing will ever clear."""
        if session_id not in self._active_sessions:
            return False
        if not self._session_task_is_stale(session_id):
            return False
        logger.warning(
            "[%s] healing stale session lock for %s (owner task done/absent)",
            self.name,
            session_id,
        )
        self._active_sessions.pop(session_id, None)
        self._pending_messages.pop(session_id, None)
        self._session_tasks.pop(session_id, None)
        return True

    def _release_session_guard(
        self,
        session_id: str,
        *,
        guard: asyncio.Event | None = None,
    ) -> None:
        """Release the adapter-level guard for a session.

        When ``guard`` is given, only release if the stored entry is
        that exact Event. Command-scoped guards (installed by
        :meth:`_dispatch_active_session_command`) use this identity
        check so a stale finally-block can't clobber a replacement
        guard a newer command put in place.
        """
        existing = self._active_sessions.get(session_id)
        if existing is None:
            return
        if guard is not None and existing is not guard:
            return
        self._active_sessions.pop(session_id, None)

    def _start_session_processing(
        self,
        event: MessageEvent,
        session_id: str,
        *,
        interrupt_event: asyncio.Event | None = None,
    ) -> bool:
        """Install the guard and spawn the processing task atomically.

        The guard goes into ``_active_sessions`` *before*
        ``asyncio.create_task`` — closing the race where a second
        message arriving on the same event-loop tick would also pass
        the busy check and spawn a duplicate task.

        Returns True on success. If ``create_task`` is stubbed by a
        test with a non-Task sentinel (some tests do this), the guard
        is rolled back and False is returned.
        """
        guard = interrupt_event or asyncio.Event()
        self._active_sessions[session_id] = guard

        task = asyncio.create_task(self._process_message_background(event, session_id))
        self._session_tasks[session_id] = task
        try:
            self._background_tasks.add(task)
        except TypeError:
            self._session_tasks.pop(session_id, None)
            self._release_session_guard(session_id, guard=guard)
            return False
        if hasattr(task, "add_done_callback"):
            task.add_done_callback(self._background_tasks.discard)
            task.add_done_callback(self._expected_cancelled_tasks.discard)
        return True

    async def cancel_session_processing(
        self,
        session_id: str,
        *,
        release_guard: bool = True,
        discard_pending: bool = True,
        timeout: float = 5.0,
    ) -> None:
        """Cancel the in-flight task for ``session_id``.

        Bounded by ``timeout`` so a wedged ``finally`` block in the
        cancelled task (typing-task cleanup, etc.) can't stall the
        caller. ``release_guard=False`` keeps the guard in place so
        a reset-style command can finish atomically before follow-ups
        start a fresh task.
        """
        task = self._session_tasks.pop(session_id, None)
        if task is not None and not task.done():
            self._expected_cancelled_tasks.add(task)
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                logger.debug(
                    "[%s] session cancellation raised while unwinding %s",
                    self.name,
                    session_id,
                    exc_info=True,
                )
        if discard_pending:
            self._pending_messages.pop(session_id, None)
        if release_guard:
            self._release_session_guard(session_id)

    async def _drain_pending_after_session_command(
        self,
        session_id: str,
        command_guard: asyncio.Event,
    ) -> None:
        """Tail of a ``/stop|/new|/reset`` dispatch: release the
        command-scoped guard, then spawn a fresh processing task if a
        follow-up landed while the command was running."""
        pending_event = self._pending_messages.pop(session_id, None)
        self._release_session_guard(session_id, guard=command_guard)
        if pending_event is None:
            return
        self._start_session_processing(pending_event, session_id)

    async def _dispatch_active_session_command(
        self,
        event: MessageEvent,
        session_id: str,
        cmd: str,
    ) -> None:
        """``/stop``, ``/new``, ``/reset`` while the session is busy.

        Sequence (Hermes PR #4926):

        1. Install a command-scoped guard so any racing follow-up
           queues into pending instead of spawning a parallel task.
        2. Run the command, send its response.
        3. Cancel the old in-flight task *after* the response sends —
           so the send is never affected by cancellation side-effects.
        4. Release the command-scoped guard and, if a follow-up
           landed, spawn a fresh processing task for it.
        """
        logger.debug(
            "[%s] command '/%s' bypassing active-session guard for %s",
            self.name,
            cmd,
            session_id,
        )
        current_guard = self._active_sessions.get(session_id)
        command_guard = asyncio.Event()
        self._active_sessions[session_id] = command_guard

        try:
            await self._handle_bypass_command(event, session_id, cmd)
            await self.cancel_session_processing(
                session_id,
                release_guard=False,
                discard_pending=False,
            )
        except Exception:
            # Restore the prior guard so we don't leave the session in
            # a half-reset state if the bypass dispatch itself failed.
            if self._active_sessions.get(session_id) is command_guard:
                if session_id in self._session_tasks and current_guard is not None:
                    self._active_sessions[session_id] = current_guard
                else:
                    self._release_session_guard(session_id, guard=command_guard)
            raise

        await self._drain_pending_after_session_command(session_id, command_guard)

    async def _dispatch_bypass_command(
        self,
        event: MessageEvent,
        session_id: str,
        cmd: str,
    ) -> None:
        """``/approve``, ``/deny``, ``/status``, ``/restart`` while the
        session is busy. Inline dispatch — these don't cancel the
        running task; they unblock or report on it."""
        logger.debug(
            "[%s] command '/%s' inline-bypass for %s",
            self.name,
            cmd,
            session_id,
        )
        try:
            await self._handle_bypass_command(event, session_id, cmd)
        except Exception:
            logger.exception(
                "[%s] bypass command '/%s' dispatch failed",
                self.name,
                cmd,
            )

    async def _handle_bypass_command(
        self,
        event: MessageEvent,
        session_id: str,
        cmd: str,
    ) -> None:
        """Run a bypass command and send its response. The default
        implementation delegates to the daemon's command dispatcher
        (added in Prompt 10.2). Overridable by subclasses that want
        platform-specific UI for some commands."""
        response = await self.daemon.dispatch_command(event, session_id, cmd)
        if response:
            await self.send_text(event.chat_id, response)

    # ---- per-message work loop ----

    async def _process_message_background(
        self,
        event: MessageEvent,
        session_id: str,
    ) -> None:
        """Run one inbound message to completion: warm the agent,
        install the gateway approval bridge, fire ``run_until_done``
        on a worker thread, stream the result back to the chat, and
        drain pending follow-ups.

        Lifecycle, in order:

        1. Acquire the agent from the pool (warm-cache hit reuses an
           in-memory instance; miss instantiates and replays JSONL).
        2. Spawn a "typing heartbeat" task that keeps the platform's
           typing indicator alive while the worker thread runs.
        3. Install :func:`build_gateway_approval_callback` via a
           context-var. The worker thread inherits the context, so
           tool dispatch sees this callback instead of the default
           terminal ``ui.confirm``.
        4. ``asyncio.to_thread(agent.run_until_done, event.text)`` —
           the agent loop runs synchronously; tool calls that need
           approval cross back into the loop via
           ``ApprovalRouter.request_sync``.
        5. Send the final assistant message (chunked to the
           platform's body cap) via :meth:`send_text`.
        6. ``finally``: cancel the typing task, reset the approval
           context, release the session guard, drain any pending
           follow-up into a fresh task.

        Cancellation: if a follow-up message sets
        ``self._active_sessions[session_id]`` (the interrupt event)
        mid-run, the agent's tool loop won't know about it (it's
        running synchronously on a worker thread), so the interrupt
        only takes effect at the START of the next turn — when the
        base's ``handle_inbound`` sees the merged pending event and
        decides whether to spawn a new task. The merged event is
        consumed in the drain step below.
        """
        import asyncio
        import time

        from ..agent.media_artifacts import reset_media_sink, set_media_sink
        from ..agent.progress import reset_progress_sink, set_progress_sink
        from ..agent.tool_relay import reset_tool_result_sink, set_tool_result_sink
        from ..safety.approval_callback import (
            reset_approval_callback,
            set_approval_callback,
        )
        from .agent_factory import build_gateway_approval_callback

        guard = self._active_sessions.get(session_id)
        # Start the typing indicator BEFORE pool.use. A cold-cache
        # session pays the full agent-build cost inside pool.use
        # (provider show_model HTTP, ATHENA.md read, sqlite open, skills
        # discovery walk, JSONL replay); without the heartbeat already
        # running, that whole window is dead air on the very first
        # message of a conversation. Cancelled in the outer finally.
        heartbeat_task = asyncio.create_task(
            self._typing_heartbeat(event.chat_id),
            name=f"gateway-typing-{session_id[:8]}",
        )
        try:
            # ``pool.use`` refcount-pins the entry so concurrent
            # eviction won't close the agent (and its owned
            # SessionStore) while the run_turn below is in flight.
            # Closing mid-dispatch produced "Cannot operate on a
            # closed database" sqlite warnings under stress.
            try:
                pool_ctx = self.daemon.pool.use(session_id)
                agent = await pool_ctx.__aenter__()
            except Exception:
                logger.exception(
                    "[%s] agent pool.use failed for %s",
                    self.name,
                    session_id,
                )
                await self._safe_send(
                    event.chat_id,
                    "_failed to load session; check logs_",
                )
                return

            try:
                approval_callback = build_gateway_approval_callback(
                    self.daemon,
                    session_id=session_id,
                    platform=self.name,
                    chat_id=event.chat_id,
                )
                approval_token = set_approval_callback(approval_callback)

                # Progress bridge: the agent loop runs synchronously on
                # a worker thread and calls emit_progress() at each tool
                # round. Ship those lines to the chat so a long
                # multi-tool turn shows life instead of dead air behind
                # the typing indicator. Fire-and-forget onto the loop;
                # the worker thread never blocks on the send. Throttled
                # so a tool-heavy turn doesn't trip platform rate limits
                # or bury the channel.
                loop = asyncio.get_running_loop()
                last_progress = [0.0]

                def _progress_sink(message: str) -> None:
                    now = time.monotonic()
                    # Always let the first line through; throttle the rest.
                    if last_progress[0] and now - last_progress[0] < _PROGRESS_MIN_INTERVAL_SECONDS:
                        return
                    last_progress[0] = now
                    loop.call_soon_threadsafe(
                        lambda: self._background_tasks.add(
                            asyncio.create_task(self._safe_send(event.chat_id, f"_{message}_"))
                        )
                    )

                progress_token = set_progress_sink(_progress_sink)

                # Media bridge: tools that render a local file (video /
                # image) call emit_media_artifact(path). Collect the
                # paths on the worker thread, then send_file() each into
                # the chat after the turn — otherwise a generated video
                # only ever leaves the user a server-side path they
                # can't reach.
                media_artifacts: list[str] = []
                media_token = set_media_sink(media_artifacts.append)

                # Tool-result relay: a tool that declared gateway_relay
                # (e.g. skills_list) emits its result here; we collect
                # them on the worker thread and deliver them to the chat
                # after the turn — the output IS what the user asked to
                # see, and it otherwise only renders to the daemon's
                # terminal.
                relayed_results: list[tuple[str, str]] = []
                relay_token = set_tool_result_sink(
                    lambda tool_name, text: relayed_results.append((tool_name, text))
                )

                user_text = _build_user_text(event)

                try:
                    await asyncio.to_thread(
                        agent.run_until_done,
                        user_text,
                    )
                except Exception as exc:
                    logger.exception(
                        "[%s] agent run failed for %s",
                        self.name,
                        session_id,
                    )
                    await self._safe_send(
                        event.chat_id,
                        f"_processing failed — {_format_run_error(exc)}_\n"
                        "_(full trace in the daemon log)_",
                    )
                    return
                finally:
                    reset_tool_result_sink(relay_token)
                    reset_media_sink(media_token)
                    reset_progress_sink(progress_token)
                    reset_approval_callback(approval_token)

                # Relayed tool output first (the content the user asked
                # for), then the model's summary, then any media files.
                await self._send_tool_results(event.chat_id, relayed_results)
                response = strip_think_blocks(agent.last_assistant_message()).strip()
                if response:
                    await self._send_chunked(event.chat_id, response)
                await self._send_media_artifacts(event.chat_id, media_artifacts)
            finally:
                await pool_ctx.__aexit__(None, None, None)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._session_tasks.pop(session_id, None)
            pending = self._pending_messages.pop(session_id, None)
            if guard is not None:
                self._release_session_guard(session_id, guard=guard)
            if pending is not None:
                # A follow-up arrived while we were running — kick off
                # a fresh processing task so it doesn't sit waiting for
                # someone to send another message before being picked up.
                self._start_session_processing(pending, session_id)

    # ---- typing heartbeat ----

    async def _typing_heartbeat(self, chat_id: str) -> None:
        """Keep the platform's typing indicator alive while the agent
        runs. Each call to :meth:`show_typing` is one-shot — Telegram
        shows ~5s, Discord ~10s — so we re-fire on a short cadence.

        Cancelled by :meth:`_process_message_background` once the
        worker thread returns.
        """
        import asyncio

        try:
            while True:
                show = getattr(self, "show_typing", None)
                if show is not None:
                    try:
                        await show(chat_id)
                    except Exception:
                        logger.debug(
                            "[%s] show_typing raised",
                            self.name,
                            exc_info=True,
                        )
                await asyncio.sleep(_TYPING_REFRESH_SECONDS)
        except asyncio.CancelledError:
            return

    # ---- send helpers ----

    async def _safe_send(self, chat_id: str, text: str) -> None:
        try:
            await self.send_text(chat_id, text)
        except Exception:
            logger.exception(
                "[%s] error-path send failed for %s",
                self.name,
                chat_id,
            )

    async def _send_tool_results(self, chat_id: str, results: list[tuple[str, str]]) -> None:
        """Deliver the results of gateway_relay tools into the chat.

        Each result gets a short ``_tool:_`` header and its body, the
        body truncated to :data:`_TOOL_RELAY_CHAR_CAP` (with a note) and
        then chunked to the platform's body cap. A per-turn cap bounds
        how many results a single turn can post so a tool-heavy turn
        can't flood the channel; the rest are logged and dropped. Empty
        results are skipped. One result failing never aborts the rest.
        """
        if not results:
            return
        sent = 0
        for name, body in results:
            text = (body or "").strip()
            if not text:
                continue
            if sent >= _MAX_TOOL_RELAYS_PER_TURN:
                logger.warning(
                    "[%s] tool-relay cap (%d) reached; %d result(s) not sent",
                    self.name,
                    _MAX_TOOL_RELAYS_PER_TURN,
                    len(results) - sent,
                )
                break
            if len(text) > _TOOL_RELAY_CHAR_CAP:
                dropped = len(text) - _TOOL_RELAY_CHAR_CAP
                text = text[:_TOOL_RELAY_CHAR_CAP] + f"\n… (truncated; {dropped} more chars)"
            try:
                await self._send_chunked(chat_id, f"_{name}:_\n{text}")
                sent += 1
            except Exception:
                logger.exception(
                    "[%s] failed to relay result of %s to %s",
                    self.name,
                    name,
                    chat_id,
                )

    async def _send_media_artifacts(self, chat_id: str, paths: list[str]) -> None:
        """Deliver media files a turn produced (video/image) into the
        chat via :meth:`send_file`.

        Deduplicates while preserving order and skips paths that don't
        point at an existing file (a tool may have reported a failure
        payload, or the file was cleaned up). A per-turn cap guards
        against a runaway loop spamming the channel; anything dropped
        is logged. One file failing to send never aborts the rest.
        """
        if not paths:
            return
        seen: set[str] = set()
        sent = 0
        for raw in paths:
            if not raw or raw in seen:
                continue
            seen.add(raw)
            path = Path(raw)
            if not path.is_file():
                logger.warning(
                    "[%s] media artifact %s is not a file; skipping",
                    self.name,
                    raw,
                )
                continue
            if sent >= _MAX_MEDIA_ARTIFACTS_PER_TURN:
                logger.warning(
                    "[%s] media artifact cap (%d) reached; %d more not sent",
                    self.name,
                    _MAX_MEDIA_ARTIFACTS_PER_TURN,
                    len(seen) - sent,
                )
                break
            try:
                await self.send_file(chat_id, path)
                sent += 1
            except Exception:
                logger.exception(
                    "[%s] failed to send media artifact %s",
                    self.name,
                    raw,
                )
                await self._safe_send(
                    chat_id,
                    f"_(generated {path.name} but couldn't attach it; "
                    f"it's saved on the server at {path})_",
                )

    async def _send_chunked(self, chat_id: str, text: str) -> None:
        """Send a long body in platform-respecting chunks.

        Default ceiling is :data:`_DEFAULT_BODY_CAP` (~3500 chars —
        below Telegram's 4096 hard cap with headroom for parse_mode
        markers). Subclasses can override :attr:`body_cap` for tighter
        platform limits (Discord is 2000).

        Chunks split on the nearest paragraph or sentence boundary
        when possible; on no boundary in the budget, hard-cut.
        """
        cap = getattr(self, "body_cap", _DEFAULT_BODY_CAP)
        chunks = list(_chunk_text(text, cap))
        for i, chunk in enumerate(chunks):
            try:
                await self.send_text(chat_id, chunk)
            except Exception:
                # Log and continue rather than abort the whole reply:
                # one oversized / format-tripping chunk shouldn't
                # swallow the rest of the assistant's turn. The user
                # sees the partial answer + a clear failure marker
                # instead of silence.
                logger.exception(
                    "[%s] send_text failed for %s chunk %d/%d",
                    self.name,
                    chat_id,
                    i + 1,
                    len(chunks),
                )
                try:
                    await self.send_text(
                        chat_id,
                        f"_(chunk {i + 1}/{len(chunks)} failed to send; see daemon log)_",
                    )
                except Exception:
                    pass


# ---- module-level helpers ----------------------------------------------


def _RUN_ERROR_CAP() -> int:
    return 240


def _format_run_error(exc: BaseException) -> str:
    """Render a chat-safe one-line summary of a turn failure.

    A Discord user has no terminal, so a bare "processing failed" leaves
    them blind. This surfaces the exception type + message (e.g.
    ``TimeoutError: ...`` from a wedged local model, or an xAI HTTP
    code) so they can see WHAT broke. Bounded length; the full trace
    still goes to the daemon log. Best-effort — never raises.
    """
    try:
        name = type(exc).__name__
        msg = str(exc).strip().replace("\n", " ")
        summary = f"{name}: {msg}" if msg else name
        cap = _RUN_ERROR_CAP()
        if len(summary) > cap:
            summary = summary[:cap].rstrip() + "…"
        return summary
    except Exception:  # noqa: BLE001 — error formatting must not raise
        return "unexpected error"


def _build_user_text(event: MessageEvent) -> str:
    """Compose the user-text the agent sees.

    For text events: ``event.text`` straight through. For events with
    attachments, append a short note listing the cached file paths so
    the agent can read them with file tools — the tool layer doesn't
    know about Telegram / Slack / Discord media URLs, but it can
    happily ``cat`` a local file the adapter saved into the per-chat
    attachment dir.
    """
    text = event.text or ""
    if not event.attachments:
        return text
    note_lines = ["", "[attached files — read via file tools]"]
    for path in event.attachments:
        note_lines.append(f"  {path}")
    return text + "\n".join(note_lines) if text else "\n".join(note_lines[1:])


def _chunk_text(text: str, cap: int) -> list[str]:
    """Split ``text`` into chunks no longer than ``cap`` characters.

    Prefers paragraph (``\\n\\n``) boundaries, then single-newline,
    then sentence-end punctuation, then word boundaries; falls back
    to a hard slice if no boundary fits.
    """
    if not text:
        return []
    if len(text) <= cap:
        return [text]

    chunks: list[str] = []
    remaining = text
    # Tiny-chunk floor avoids splitting on a punctuation/space that
    # lands very early in the budget. Paragraph boundaries are
    # exempt — those are intentional structural breaks the agent
    # author chose, and respecting them matters more than chunk
    # balance.
    tiny_floor = int(cap * 0.6)
    while len(remaining) > cap:
        window = remaining[:cap]
        split_at = cap
        for sep, floor in (
            ("\n\n", 1),
            ("\n", tiny_floor),
            (". ", tiny_floor),
            (" ", tiny_floor),
        ):
            idx = window.rfind(sep)
            if idx >= floor:
                split_at = idx + len(sep)
                break
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
