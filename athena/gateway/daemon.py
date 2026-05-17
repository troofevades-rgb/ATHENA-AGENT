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
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from ..config import Config, profile_dir
from ..sessions.store import SessionStore
from .agent_pool import AgentFactory, AgentPool
from .events import MessageEvent
from .router import SessionRouter

if TYPE_CHECKING:
    from ..agent.core import Agent
    from .base import GatewayAdapter

logger = logging.getLogger(__name__)


# A command dispatcher: ``(event, session_id, cmd) -> response_text``.
# Returning the empty string suppresses the adapter's reply.
CommandDispatcher = Callable[[MessageEvent, str, str], Awaitable[str]]


async def _stub_dispatch(
    event: MessageEvent, session_id: str, cmd: str
) -> str:
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
        # Phase 10.8 plugs in a real factory that loads conversation
        # history from the session's JSONL. The stub factory exists so
        # AgentPool can be tested in isolation here.
        self.pool = AgentPool(
            agent_factory or _stub_agent_factory,
            max_size=gw.max_warm_agents,
        )
        self._dispatch_command = command_dispatcher or _stub_dispatch
        self.adapters: list["GatewayAdapter"] = []
        self._adapter_tasks: list[asyncio.Task] = []
        self._started = False

    # ---- adapter lifecycle ----

    def register(self, adapter: "GatewayAdapter") -> None:
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
        task and return. Subsequent calls are no-ops."""
        if self._started:
            return
        self._started = True
        for adapter in self.adapters:
            task = asyncio.create_task(
                adapter.start(),
                name=f"gateway-adapter-{adapter.name}",
            )
            self._adapter_tasks.append(task)

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
                    "adapter %s.stop() raised: %r", adapter.name, exc,
                )

        for task in self._adapter_tasks:
            if not task.done():
                task.cancel()
        self._adapter_tasks.clear()

        await self.pool.evict_all()
        self.router.close()

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
                cmd, session_id,
            )
            return f"(command /{cmd} failed; see logs)"


# ---- helpers ------------------------------------------------------------


async def _bounded_stop(adapter: "GatewayAdapter") -> None:
    try:
        await asyncio.wait_for(adapter.stop(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning(
            "adapter %s.stop() exceeded 10s; continuing shutdown",
            adapter.name,
        )


async def _stub_agent_factory(session_id: str) -> "Agent":
    """Phase 10.2 placeholder. Phase 10.8 ships the real factory.

    Raising rather than constructing avoids accidentally booting a
    half-wired agent during the pre-streaming phases."""
    raise NotImplementedError(
        f"agent_factory not configured (session_id={session_id}); "
        "the real factory lands in Phase 10.8 alongside _process wire-up"
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
