"""ACP method handlers.

:func:`register(server, agent_factory)` wires the seven JSON-RPC
methods the ACP spec requires into the given :class:`ACPServer`:

- ``initialize`` — handshake; returns capabilities, server info, and
  protocol version.
- ``session/new`` — instantiate an :class:`Agent` and track it.
- ``session/end`` — close the agent and drop the entry.
- ``session/send_message`` — the workhorse. Run one turn on the
  agent (sync, via ``asyncio.to_thread``), stream content + tool
  calls back to the IDE, and return when complete. Each tool call
  that wants confirmation routes through the ACP
  ``permission_request`` bridge.
- ``session/cancel`` — set ``Agent.cancel_pending = True`` so the
  in-flight turn aborts at the next tool-call boundary.
- ``session/slash_command`` — route ``/steer``, ``/queue``, ``/goal``
  through :mod:`.slash_commands`.
- ``models/list`` — return every (provider, model) the resolver
  would route to today; useful for IDE model pickers.

``agent_factory`` is a ``() -> Agent`` callable. The CLI passes one
that constructs an Agent against the current profile / workspace /
config. Tests pass a stub.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..safety.approval_callback import (
    reset_approval_callback,
    set_approval_callback,
)
from .capabilities import CAPABILITIES, PROTOCOL_VERSION, SERVER_INFO
from .slash_commands import handle_slash
from .streaming import StreamingSender

if TYPE_CHECKING:
    from ..agent.core import Agent
    from .server import ACPServer

logger = logging.getLogger(__name__)


AgentFactory = Callable[[], "Agent"]


def register(
    server: ACPServer,
    agent_factory: AgentFactory,
) -> dict[str, Agent]:
    """Wire every method handler onto ``server`` and return the live
    sessions dict so callers (the CLI's shutdown path, tests, etc.)
    can introspect it.
    """
    sessions: dict[str, Agent] = {}

    @server.method("initialize")
    async def _initialize(_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "server_info": SERVER_INFO,
            "capabilities": CAPABILITIES,
        }

    @server.method("session/new")
    async def _session_new(params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("session_id") or _generate_session_id())
        if sid in sessions:
            return {"session_id": sid}  # idempotent
        # Construction may do I/O (provider.show_model HTTP, ATHENA.md
        # read, skills walk). Push to a thread so we don't block the
        # event loop.
        agent = await asyncio.to_thread(agent_factory)
        sessions[sid] = agent
        return {"session_id": sid}

    @server.method("session/end")
    async def _session_end(params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("session_id") or "")
        agent = sessions.pop(sid, None)
        if agent is None:
            return {"closed": False}
        try:
            close = getattr(agent, "close", None)
            if close is not None:
                await asyncio.to_thread(close)
        except Exception:
            logger.exception("agent.close failed during session/end")
        return {"closed": True}

    @server.method("session/send_message")
    async def _send_message(params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("session_id") or "")
        message = params.get("message") or {}
        agent = sessions.get(sid)
        if agent is None:
            return {"error": f"no such session: {sid}"}
        user_text = _coerce_user_text(message)
        sender = StreamingSender(server, sid)

        await sender.turn_started()
        # Open a text block; the buffered model means we ship one
        # delta after the agent finishes (real chunk streaming is a
        # follow-up). Either way, the surrounding start/stop blocks
        # let the IDE render the response in its dedicated panel.
        await sender.text_block_start("text-0")

        approval_callback = _build_approval_callback(server, sid)
        approval_token = set_approval_callback(approval_callback)
        try:
            await asyncio.to_thread(agent.run_until_done, user_text)
        except Exception as e:
            logger.exception("[acp] agent run failed for %s", sid)
            await sender.text_delta(f"\n_processing failed: {e}_\n")
            await sender.text_block_stop("text-0")
            await sender.turn_completed(reason="error")
            return {"completed": False, "error": str(e)}
        finally:
            reset_approval_callback(approval_token)

        final = agent.last_assistant_message()
        if final:
            await sender.text_delta(final)
        await sender.text_block_stop("text-0")

        # Surface every tool call the turn produced so the IDE can
        # render them in its activity panel. Buffered for the same
        # reason as the text — real per-call streaming lands in a
        # follow-up.
        for call in agent.tool_call_trace():
            fn = call.get("function") or {}
            tool_id = call.get("id") or _generate_tool_id()
            await sender.tool_call_start(
                tool_id,
                fn.get("name", "?"),
                fn.get("arguments") or {},
            )
        reason = "cancelled" if agent.cancel_pending else "stop"
        await sender.turn_completed(reason=reason)
        return {"completed": True, "reason": reason}

    @server.method("session/cancel")
    async def _cancel(params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("session_id") or "")
        agent = sessions.get(sid)
        if agent is None:
            return {"cancelled": False}
        agent.cancel_pending = True
        return {"cancelled": True}

    @server.method("session/slash_command")
    async def _slash(params: dict[str, Any]) -> dict[str, Any]:
        return await handle_slash(params, sessions)

    @server.method("models/list")
    async def _models(_params: dict[str, Any]) -> dict[str, Any]:
        return {"models": _list_available_models()}

    return sessions


# ---- helpers -------------------------------------------------------


def _coerce_user_text(message: dict[str, Any]) -> str:
    """Pull a plain string out of the IDE's ``message`` payload.

    ACP messages can be a bare string, a ``{"text": "..."}`` dict, or
    a content-block array like Anthropic's. We accept all three so
    different IDEs interop.
    """
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    if isinstance(message.get("text"), str):
        return message["text"]
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _build_approval_callback(server: ACPServer, session_id: str):
    """Return a sync approval callback that bridges into
    :meth:`StreamingSender.permission_request` via
    ``asyncio.run_coroutine_threadsafe``.

    The bridge is the same shape as the gateway's
    ``build_gateway_approval_callback``: the worker thread (where
    ``agent.run_until_done`` runs) calls the sync callback; that
    callback submits a coroutine onto the loop running ``serve()``
    and blocks on the result.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside a running loop — fall back to deny.
        return _auto_deny_callback

    def callback(tool_name: str, args: dict[str, Any]) -> str:
        sender = StreamingSender(server, session_id)
        cf = asyncio.run_coroutine_threadsafe(
            sender.permission_request(tool_name, args),
            loop,
        )
        try:
            return cf.result(timeout=310.0)
        except Exception:
            logger.exception("[acp] permission bridge failed")
            return "deny"

    return callback


def _auto_deny_callback(tool_name: str, args: dict[str, Any]) -> str:
    logger.warning(
        "[acp] approval callback fired with no event loop; denying %s",
        tool_name,
    )
    return "deny"


def _generate_session_id() -> str:
    return f"acp-{secrets.token_hex(8)}"


def _generate_tool_id() -> str:
    return f"call-{secrets.token_hex(6)}"


def _list_available_models() -> list[dict[str, str]]:
    """Enumerate every (provider, model) the resolver would accept.

    Pulls from the registered providers' ``list_models``; failures
    skip that provider rather than abort.
    """
    try:
        from ..config import load_config
        from ..providers import _REGISTRY
        from ..providers.credential_pool import profile_pool
    except ImportError:
        return []

    out: list[dict[str, str]] = []
    cfg = load_config()
    pool = profile_pool(cfg.profile)
    for name in sorted(_REGISTRY.keys()):
        try:
            provider_cls = _REGISTRY[name]
            kwargs: dict[str, Any] = {}
            if provider_cls.requires_api_key:
                cred = pool.get(name)
                if cred is None:
                    continue
                kwargs["api_key"] = cred
            else:
                kwargs["host"] = cfg.ollama_host
            client = provider_cls(**kwargs)
            try:
                for model in client.list_models():
                    out.append({"provider": name, "model": str(model)})
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        except Exception:
            logger.debug(
                "skip provider %s in models/list",
                name,
                exc_info=True,
            )
            continue
    return out
