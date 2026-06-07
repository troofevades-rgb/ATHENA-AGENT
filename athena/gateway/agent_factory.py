"""Wire the gateway daemon's :class:`AgentPool` to real :class:`Agent`s.

Phase 10.2 shipped the pool with a stub factory that raised
``NotImplementedError``. Phase 10.8 replaces it with this module: an
async factory that constructs an :class:`Agent` bound to the daemon's
shared :class:`SessionStore`, replays the session's JSONL into
``Agent.messages``, and hands it back to the pool warm and ready.

The factory also wires the per-turn approval callback. Tools that
opt into ``check_fn`` confirmation prompts call
:func:`get_approval_callback`; the gateway-flavored callback returned
by :func:`build_gateway_approval_callback` routes the prompt through
:class:`ApprovalRouter.request_sync` so the user sees a platform
button instead of a terminal ``ui.confirm`` (and the worker thread
that fired the tool blocks on the cross-thread bridge until the
user clicks).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..agent.core import Agent
    from .daemon import GatewayDaemon

logger = logging.getLogger(__name__)


def build_agent_factory(
    daemon: GatewayDaemon,
) -> Callable[[str], Awaitable[Agent]]:
    """Return an async ``(session_id) -> Agent`` factory bound to
    ``daemon``. The factory closes over the daemon's session store,
    config, and profile dir; it does NOT close over a specific
    session id, so the pool can reuse it across sessions.
    """

    async def factory(session_id: str) -> Agent:
        # Defer to thread because Agent.__init__ does synchronous I/O
        # (provider.show_model HTTP, ATHENA.md read, sqlite open,
        # skills discovery walk) that would block the event loop.
        import asyncio

        return await asyncio.to_thread(_build_agent_sync, daemon, session_id)

    return factory


def _build_agent_sync(daemon: GatewayDaemon, session_id: str) -> Agent:
    """Construct a gateway-bound agent on the calling thread.

    The agent shares the daemon's :class:`SessionStore` (don't open a
    new one — that would double-open the SQLite db and lose write
    visibility across pool entries). The workspace is the profile
    dir; gateway sessions don't have a "project workspace" the way a
    foreground CLI run does.
    """
    from ..agent.core import Agent

    agent = Agent(
        daemon.cfg,
        daemon.profile_dir,
        model=daemon.cfg.model,
        session_store=daemon.session_store,
        resume_session_id=session_id,
    )
    # Gateway turns suppress the background-review fork: its child agent
    # competes with the user-facing reply for the local Ollama inference
    # slot (a chat turn can crawl or stall), and a chat user never sees
    # the review's suggestions anyway. Read by AgentRuntime._maybe_fire_review.
    # The flag is not a declared Agent attribute (runtime reads it via getattr
    # with a False default), so the assignment is dynamic.
    agent._suppress_background_review = True  # type: ignore[attr-defined]
    try:
        loaded = agent.load_history_from_session(session_id)
        if loaded:
            logger.info(
                "gateway: resumed session %s (%d turns loaded)",
                session_id[:8],
                loaded,
            )
    except Exception:
        # History reload failed mid-stream (e.g. one corrupt JSONL
        # line). The previous behaviour left ``messages = [system]``
        # and kept the SAME session_id, so subsequent turns appended
        # onto the still-broken JSONL -- compounding the corruption
        # while the user saw an agent with full amnesia about an
        # apparently-resumed chat. Detach this agent from the broken
        # session_id (the daemon's next resolve will mint a fresh
        # one) so further writes don't pile on top of the corruption.
        logger.exception(
            "gateway: history reload failed for %s; detaching session id "
            "and starting fresh -- the corrupt JSONL is preserved on disk "
            "for manual recovery",
            session_id,
        )
        agent.session_id = None
    return agent


def build_gateway_approval_callback(
    daemon: GatewayDaemon,
    *,
    session_id: str,
    platform: str,
    chat_id: str,
    timeout: float | None = None,
) -> Callable[[str, dict[str, Any]], str]:
    """Return a sync approval callback that bridges into
    :meth:`ApprovalRouter.request_sync`.

    Used by :meth:`GatewayAdapter._process_message_background` —
    installed via :func:`set_approval_callback` on the worker thread
    so the agent's tool dispatch sees it instead of the default
    terminal prompt. Captures the (session_id, platform, chat_id)
    triple in the closure so the router can render the prompt to the
    right chat without the agent needing to know about gateway
    plumbing.
    """

    def callback(tool_name: str, args: dict[str, Any]) -> str:
        return daemon.approvals.request_sync(
            session_id=session_id,
            tool_name=tool_name,
            tool_args=dict(args or {}),
            platform=platform,
            chat_id=chat_id,
            timeout=timeout,
        )

    return callback
