"""GatewayDaemon — process-wide hub for the gateway subsystem.

Owns the :class:`SessionRouter`, the :class:`AgentPool`, the shared
:class:`SessionStore`, and the list of registered platform adapters.
``handle_inbound`` on every adapter reads ``self.daemon.router``,
``self.daemon.pool`` etc., so this object is what threads the
gateway together.

Lifecycle:

- :meth:`register` adds an adapter (called by the CLI's gateway
  bootstrap before :meth:`start`).
- :meth:`start` kicks each adapter's ``start()`` coroutine as a
  background task and returns. Adapters' polling loops / websocket
  reads run concurrently from that point.
- :meth:`stop` awaits every adapter's ``stop()`` and then evicts the
  whole agent pool (flushing any unsaved session state).

Slash-command dispatch (``/stop``, ``/new``, ``/approve``, …) lives in
:meth:`dispatch_command`. Phase 10.2 ships a stub that returns a
"command not implemented" placeholder; Phase 10.3 wires in the
approval router, and Phase 10.7 routes the rest to the CLI command
table.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import Config, profile_dir
from ..sessions.store import SessionStore
from . import registry
from .agent_pool import AgentFactory, AgentPool
from .approval_routing import ApprovalRouter
from .continuity import ContinuityManager
from .events import MessageEvent
from .router import SessionRouter

if TYPE_CHECKING:
    from .base import GatewayAdapter

logger = logging.getLogger(__name__)


# A command dispatcher: ``(event, session_id, cmd) -> response_text``.
# Returning the empty string suppresses the adapter's reply.
CommandDispatcher = Callable[[MessageEvent, str, str], Awaitable[str]]


async def _stub_dispatch(event: MessageEvent, session_id: str, cmd: str) -> str:
    return f"(command /{cmd} not yet implemented)"


class GatewayDaemon:
    """Top-level coordinator. One daemon per process.

    The daemon does NOT construct adapters itself — the CLI bootstrap
    instantiates each enabled adapter (passing the daemon as
    ``daemon=``) and calls :meth:`register`. This keeps the daemon
    free of platform-specific imports so a Telegram-only deploy
    doesn't pay the cost of importing slack-sdk and discord.py.
    """

    def __init__(
        self,
        cfg: Config,
        *,
        agent_factory: AgentFactory | None = None,
        command_dispatcher: CommandDispatcher | None = None,
    ) -> None:
        self.cfg = cfg
        profile_name = cfg.profile or "default"
        self.profile_dir: Path = profile_dir(profile_name)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.session_store = SessionStore(self.profile_dir)
        gw = cfg.gateway
        self.router = SessionRouter(
            self.profile_dir,
            self.session_store,
            profile=profile_name,
            model=cfg.model,
            provider=_default_provider_name(cfg),
            continuity=gw.continuity,
        )
        # Real factory loads conversation history from the session's
        # JSONL and binds the agent to the daemon's shared SessionStore.
        # Tests can override via the agent_factory kwarg.
        if agent_factory is None:
            from .agent_factory import build_agent_factory

            agent_factory = build_agent_factory(self)
        self.pool = AgentPool(
            agent_factory,
            max_size=gw.max_warm_agents,
        )
        self.approvals = ApprovalRouter()
        self.continuity = ContinuityManager(self.router)
        self._dispatch_command = command_dispatcher or _stub_dispatch
        self.adapters: list[GatewayAdapter] = []
        self._adapter_tasks: list[asyncio.Task] = []
        self._started = False
        # Webhook listener (Phase 15) — constructed lazily in start()
        # so daemons running with [gateway.webhooks].enabled=false
        # don't pay the import cost.
        self._webhook_server: Any = None

    # ---- adapter lifecycle ----

    def register(self, adapter: GatewayAdapter) -> None:
        """Add a platform adapter. Must be called before :meth:`start`.

        The daemon does NOT enforce uniqueness on adapter name — two
        Telegram adapters with different bot tokens is a legitimate
        deploy (split inbox / outbox personas), even if uncommon.
        """
        if self._started:
            raise RuntimeError(
                "cannot register adapter after daemon.start() — "
                "register all adapters before starting"
            )
        self.adapters.append(adapter)

    async def start(self) -> None:
        """Kick every registered adapter's ``start()`` as a background
        task and return. Subsequent calls are no-ops.

        Binds the running event loop on the approval router so
        :meth:`ApprovalRouter.request_sync` (called from the agent's
        worker thread in Phase 10.8) has somewhere to submit work.
        """
        if self._started:
            return
        self._started = True
        self.approvals.bind_loop(asyncio.get_running_loop())
        # Register before kicking adapters so cron jobs that fire
        # during adapter startup can already find us.
        registry.register(self)
        for adapter in self.adapters:
            task = asyncio.create_task(
                adapter.start(),
                name=f"gateway-adapter-{adapter.name}",
            )

            # Without a done-callback the adapter's start() exception
            # lives forever in the orphan task and the daemon sits at
            # await stop_event.wait() with the platform in offline
            # limbo. Log the exception loudly so the operator sees
            # it instead of guessing why the bot never appears.
            def _on_done(t: asyncio.Task, _name: str = adapter.name) -> None:
                if t.cancelled():
                    return
                exc = t.exception()
                if exc is not None:
                    logger.error(
                        "[%s] adapter start() crashed: %s",
                        _name,
                        exc,
                        exc_info=exc,
                    )

            task.add_done_callback(_on_done)
            self._adapter_tasks.append(task)

        # Webhook listener — only spin it up when the user
        # explicitly enables it. Listening on a port without being
        # asked would surprise people.
        gw_cfg = self.cfg.gateway
        wh = getattr(gw_cfg, "webhooks", None)
        if wh is not None and getattr(wh, "enabled", False):
            try:
                self._webhook_server = await self._start_webhook_server(
                    wh.host,
                    wh.port,
                )
            except Exception:
                logger.exception(
                    "webhook server failed to start; continuing without it",
                )

    async def stop(self) -> None:
        """Stop every adapter, then drain the agent pool.

        ``adapter.stop()`` is bounded by a 10s shield — a wedged stop
        coroutine can't block daemon shutdown indefinitely. Each
        adapter's start-task is cancelled afterwards in case its
        polling loop didn't exit cleanly.
        """
        if not self._started:
            return
        self._started = False

        stop_results = await asyncio.gather(
            *(_bounded_stop(a) for a in self.adapters),
            return_exceptions=True,
        )
        for adapter, exc in zip(self.adapters, stop_results):
            if isinstance(exc, BaseException):
                logger.warning(
                    "adapter %s.stop() raised: %r",
                    adapter.name,
                    exc,
                )

        for task in self._adapter_tasks:
            if not task.done():
                task.cancel()
        self._adapter_tasks.clear()

        # Stop the webhook listener (if running) before tearing down
        # the pool — webhook dispatch sometimes routes through gateway
        # adapters, and the agent it spawned might still be writing
        # to one.
        if self._webhook_server is not None:
            try:
                await self._webhook_server.stop()
            except Exception:
                logger.exception("webhook server stop() raised")
            self._webhook_server = None

        # Drain in-flight per-session dispatch tasks before evicting
        # agents. Each adapter owns a dict[session_id, asyncio.Task]
        # of background message handlers; closing their agents
        # underneath them produced "Cannot operate on a closed
        # database" sqlite warnings during stress shutdown. We give
        # them a bounded grace period, then proceed regardless.
        pending: list[asyncio.Task] = []
        for adapter in self.adapters:
            for task in getattr(adapter, "_session_tasks", {}).values():
                if not task.done():
                    pending.append(task)
        if pending:
            done, _ = await asyncio.wait(
                pending,
                timeout=10.0,
                return_when=asyncio.ALL_COMPLETED,
            )
            still_running = [t for t in pending if not t.done()]
            if still_running:
                logger.warning(
                    "daemon.stop: %d session dispatch task(s) did not drain in 10s; cancelling",
                    len(still_running),
                )
                for t in still_running:
                    t.cancel()

        # Deny every pending approval so any worker thread blocked on
        # request_sync unwinds cleanly before pool.evict_all closes
        # the agents holding those threads.
        self.approvals.cancel_all()
        await self.pool.evict_all()
        self.router.close()
        registry.unregister(self)

    # ---- webhook server bootstrap ----

    async def _start_webhook_server(self, host: str, port: int):
        """Construct + start a WebhookServer wired to the same
        profile's store and a dispatch callback that closes over
        this daemon. Called from start() when
        ``cfg.gateway.webhooks.enabled`` is True."""
        from ..webhooks.delivery import dispatch_webhook
        from ..webhooks.server import WebhookServer
        from ..webhooks.subscription import WebhookStore

        store = WebhookStore(self.profile_dir / "webhooks.db")

        async def _dispatch(sub, payload, headers):
            await dispatch_webhook(
                daemon=self,
                sub=sub,
                payload=payload,
                headers=headers,
            )

        server = WebhookServer(
            daemon=self,
            store=store,
            host=host,
            port=port,
            dispatch=_dispatch,
        )
        await server.start()
        return server

    # ---- outbound shortcuts ----

    def adapter_for(self, platform: str) -> GatewayAdapter | None:
        """Return the registered adapter whose ``name`` matches
        ``platform``, or ``None``. Used by the cron delivery layer to
        route gateway:// targets to the right adapter."""
        for adapter in self.adapters:
            if adapter.name == platform:
                return adapter
        return None

    # ---- command dispatch ----

    async def dispatch_command(
        self,
        event: MessageEvent,
        session_id: str,
        cmd: str,
    ) -> str:
        """Run a slash command and return the text response.

        ``GatewayAdapter._handle_bypass_command`` calls this; the
        adapter then sends the returned text via ``send_text``. An
        empty string suppresses the reply (useful for commands that
        deliver output via other channels, e.g. ``/status`` posting a
        block-kit panel).
        """
        try:
            return await self._dispatch_command(event, session_id, cmd)
        except Exception:
            logger.exception(
                "dispatch_command failed for /%s on session %s",
                cmd,
                session_id,
            )
            return f"(command /{cmd} failed; see logs)"


# ---- helpers ------------------------------------------------------------


async def _bounded_stop(adapter: GatewayAdapter) -> None:
    try:
        await asyncio.wait_for(adapter.stop(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning(
            "adapter %s.stop() exceeded 10s; continuing shutdown",
            adapter.name,
        )


def _default_provider_name(cfg: Config) -> str:
    """Best-guess provider name from a Config. Used when minting new
    sessions so ``SessionMeta.provider`` reflects what the agent will
    actually call. Resolves at session-mint time, not at agent-spawn
    time — those can differ if the user changes models mid-conversation,
    but for the *initial* meta record this is the right read.
    """
    # The resolver's prefix routing (anthropic/, openai/, …) decides the
    # actual provider; this is a coarse echo of that. Falls back to
    # ``"ollama"`` to match the historic default.
    model = cfg.model or ""
    for prefix, name in (
        ("anthropic/", "anthropic"),
        ("openai/", "openai"),
        ("google/", "google"),
        ("openrouter/", "openrouter"),
        ("nous/", "nous"),
    ):
        if model.startswith(prefix):
            return name
    if model.startswith("gemini-"):
        return "google"
    return "ollama"
