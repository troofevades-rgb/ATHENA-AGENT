"""Approval routing for dangerous tools running over the gateway.

When a tool inside an agent turn wants user confirmation, the
gateway routes the prompt to the adapter's platform-specific UI
(Telegram inline buttons, Slack block kit, Discord ``ui.View``)
instead of the local terminal ``ui.confirm``.

The hard part is the thread/async boundary. The agent's
``approval_callback`` is a synchronous function (because the agent's
tool dispatch loop is synchronous). The platform adapter's button
handler is async (it runs inside the daemon's event loop). The
router bridges them:

- :meth:`ApprovalRouter.request_async` — called from inside the event
  loop (e.g. by an async-style tool wrapper). Awaits the decision.
- :meth:`ApprovalRouter.request_sync` — called from the agent's
  worker thread. Schedules ``request_async`` on the daemon's loop
  via :func:`asyncio.run_coroutine_threadsafe` and blocks the
  worker thread on the resulting :class:`concurrent.futures.Future`.
- :meth:`ApprovalRouter.resolve` — adapter button handler calls this
  with ``(request_id, decision)``; the matching pending future
  resolves and either ``request_async`` (loop path) or
  ``request_sync`` (thread path) unblocks.

Timeout default is 300s. On timeout, the decision is ``"deny"`` —
the safe default for any tool that asked for confirmation. Same
behavior on missing renderer / dead loop / dispatcher exceptions.

The router itself owns no I/O — adapters register a render callback
via :meth:`set_renderer` describing how to draw the approval UI.
That keeps platform code out of this module so adding a fourth
platform doesn't require touching approval routing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal

from .events import ApprovalRequest

logger = logging.getLogger(__name__)


Decision = Literal["allow", "deny"]
Renderer = Callable[[ApprovalRequest], Awaitable[None]]
"""Adapter contract: take an :class:`ApprovalRequest`, send a UI
prompt to the right chat, return (the user clicks later)."""


DEFAULT_TIMEOUT_SECONDS = 300.0


class ApprovalRouter:
    """Async + sync bridge for dangerous-tool approvals.

    One router per :class:`GatewayDaemon`. Adapters register their
    render callback at start time via :meth:`set_renderer`.
    """

    def __init__(self, *, default_timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._default_timeout = default_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._renderer: Renderer | None = None
        self._platform_renderers: dict[str, Renderer] = {}
        self._pending: dict[str, asyncio.Future[Decision]] = {}
        self._pending_records: dict[str, ApprovalRequest] = {}

    # ---- wiring ----

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Daemon calls this at :meth:`GatewayDaemon.start` so
        :meth:`request_sync` knows where to submit coroutines."""
        self._loop = loop

    def set_renderer(self, renderer: Renderer | None) -> None:
        """Install (or clear) the *default* render callback.

        Used when no platform-scoped renderer is registered for the
        request's platform. The multi-platform path
        (:meth:`register_platform_renderer`) takes priority.
        """
        self._renderer = renderer

    def register_platform_renderer(self, platform: str, renderer: Renderer | None) -> None:
        """Install a renderer scoped to one platform name. Each
        adapter calls this from its ``start()`` so dispatch is keyed
        on :attr:`ApprovalRequest.platform`.

        Pass ``renderer=None`` to remove the binding (adapter shutdown).
        """
        if renderer is None:
            self._platform_renderers.pop(platform, None)
        else:
            self._platform_renderers[platform] = renderer

    def _renderer_for(self, request: ApprovalRequest) -> Renderer | None:
        if request.platform:
            r = self._platform_renderers.get(request.platform)
            if r is not None:
                return r
        return self._renderer

    # ---- async request (loop-side) ----

    async def request_async(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        platform: str = "",
        chat_id: str = "",
        timeout: float | None = None,
    ) -> Decision:
        """Await user decision. Returns ``"deny"`` on any failure path."""
        request_id = secrets.token_hex(8)
        request = ApprovalRequest(
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            request_id=request_id,
            platform=platform,
            chat_id=chat_id,
        )

        renderer = self._renderer_for(request)
        if renderer is None:
            logger.warning(
                "approval request with no renderer installed (platform=%r); auto-denying",
                platform or "<unset>",
            )
            return "deny"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Decision] = loop.create_future()
        self._pending[request_id] = future
        self._pending_records[request_id] = request

        try:
            try:
                await renderer(request)
            except Exception:
                logger.exception(
                    "renderer raised for approval request %s; auto-denying",
                    request_id,
                )
                return "deny"

            timeout_s = timeout if timeout is not None else self._default_timeout
            try:
                decision = await asyncio.wait_for(future, timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.info(
                    "approval %s timed out after %.0fs; denying",
                    request_id,
                    timeout_s,
                )
                return "deny"
            return decision
        finally:
            self._pending.pop(request_id, None)
            record = self._pending_records.pop(request_id, None)
            if record is not None and record.answered_at is None:
                # Timeout / renderer-fail path — stamp the record so
                # adapter callbacks arriving late see "already answered".
                record.answered_at = datetime.now(timezone.utc)
                record.decision = "deny"

    # ---- sync bridge (thread-side) ----

    def request_sync(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        platform: str = "",
        chat_id: str = "",
        timeout: float | None = None,
    ) -> Decision:
        """Submit :meth:`request_async` to the daemon's loop and block
        the calling thread on the result.

        Returns ``"deny"`` if no loop is bound (gateway not running)
        or if the cross-thread bridge raises for any reason.
        """
        if self._loop is None:
            logger.warning("approval request_sync with no loop bound; denying")
            return "deny"

        # The thread-side bound is the soft timeout + a generous
        # extra so we don't race the inner asyncio.wait_for: if the
        # inner times out, request_async returns "deny" cleanly; the
        # outer concurrent-futures bound only fires if the loop itself
        # is wedged.
        soft = timeout if timeout is not None else self._default_timeout
        hard = soft + 5.0

        try:
            cf: concurrent.futures.Future[Decision] = asyncio.run_coroutine_threadsafe(
                self.request_async(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    platform=platform,
                    chat_id=chat_id,
                    timeout=timeout,
                ),
                self._loop,
            )
        except RuntimeError:
            logger.exception("loop dead during approval submission; denying")
            return "deny"

        try:
            return cf.result(timeout=hard)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "approval bridge timed out after %.0fs (loop wedged?); denying",
                hard,
            )
            cf.cancel()
            return "deny"
        except Exception:
            logger.exception("approval bridge raised; denying")
            return "deny"

    # ---- adapter callback (loop-side) ----

    def resolve(self, request_id: str, decision: Decision) -> bool:
        """Adapter calls this when the user clicks allow / deny.

        Returns True iff the request was pending and got resolved.
        Already-resolved or unknown ``request_id`` returns False —
        adapter is expected to acknowledge the click anyway (so the
        user doesn't see "no action").
        """
        future = self._pending.get(request_id)
        if future is None:
            logger.debug(
                "approval resolve called for unknown/done %s — late click?",
                request_id,
            )
            return False
        if future.done():
            return False
        record = self._pending_records.get(request_id)
        if record is not None:
            record.answered_at = datetime.now(timezone.utc)
            record.decision = decision
        future.set_result(decision)
        return True

    # ---- introspection ----

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def pending_request(self, request_id: str) -> ApprovalRequest | None:
        return self._pending_records.get(request_id)

    def cancel_all(self) -> None:
        """Daemon shutdown — deny every pending request immediately."""
        for request_id, future in list(self._pending.items()):
            if not future.done():
                future.set_result("deny")
            record = self._pending_records.get(request_id)
            if record is not None:
                record.answered_at = datetime.now(timezone.utc)
                record.decision = "deny"
