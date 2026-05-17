"""GatewayAdapter ABC — the contract every platform implements.

Each adapter speaks one platform's protocol (Telegram polling, Slack
Socket Mode, Discord gateway, ...) and normalizes both directions:

- Inbound: platform payload → :class:`~.events.MessageEvent` →
  :meth:`handle_inbound`, which routes to a session, acquires the
  session lock (with stale-lock self-heal), and spawns the processing
  task without blocking the receive loop.
- Outbound: :meth:`send_text` / :meth:`send_file` are what the
  processing task and the daemon's approval router call to talk back.

Concrete platforms only implement the four abstract methods plus, in
Phase 10.4-10.6, a couple of platform-specific extensions for approval
buttons and typing indicators. Everything else lives here so adding a
fourth platform is a single-file PR.

``_process`` — the per-message work loop — is a stub
(``NotImplementedError``) in this prompt. Prompt 10.8 implements it
once the agent pool, approval router, and streaming protocol exist.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from .events import MessageEvent
from .healing import StaleSessionLockHealer
from .heartbeat import HeartbeatTracker

if TYPE_CHECKING:
    from .daemon import GatewayDaemon  # added in Prompt 10.2

logger = logging.getLogger(__name__)


class GatewayAdapter(ABC):
    """Platform adapter base class.

    Subclasses set :attr:`name` to a stable platform slug
    (``"telegram"``, ``"slack"``, ...) and implement the four abstract
    methods. The shared :meth:`handle_inbound` orchestrates routing,
    stale-lock heal, and task spawning.
    """

    name: str = ""

    def __init__(self, daemon: "GatewayDaemon") -> None:
        self.daemon = daemon
        self._stale_lock_healer = StaleSessionLockHealer()
        self._heartbeat = HeartbeatTracker()

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

    async def handle_inbound(self, event: MessageEvent) -> None:
        """Route ``event`` to its session, heal a stale lock if any,
        and spawn the processing task.

        Returns immediately — concrete processing runs in a background
        task so the platform's receive loop keeps draining events.

        If the session is currently locked by a *live* task, the message
        is enqueued on the daemon's steer queue (so the in-flight turn
        picks it up) and a brief acknowledgement is sent back.
        """
        session_id = await self.daemon.router.resolve(event)
        lock = self.daemon.locks[session_id]

        if lock.locked() and self._stale_lock_healer.is_stale(
            session_id, self._heartbeat
        ):
            logger.warning(
                "healing stale lock for session %s on %s",
                session_id,
                self.name,
            )
            self._stale_lock_healer.force_release(lock)

        if not lock.locked():
            asyncio.create_task(self._process(event, session_id, lock))
        else:
            await self.send_text(
                event.chat_id, "_busy — queued your message_"
            )
            self.daemon.steer_queue.push(session_id, event.text)

    async def _process(
        self,
        event: MessageEvent,
        session_id: str,
        lock: asyncio.Lock,
    ) -> None:
        """Per-message work loop. Implemented in Prompt 10.8 once the
        agent pool, approval router, and streaming protocol exist."""
        raise NotImplementedError(
            "GatewayAdapter._process is implemented in Phase 10.8"
        )
