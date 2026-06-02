"""Webhook dispatch and delivery.

When a webhook authenticates and clears the rate limiter, the
server hands the parsed payload here. Two stages:

1. **Dispatch**: instantiate a one-off Agent (webhooks are
   stateless — each fire is its own conversation, not a long-lived
   session), build a prompt from the binding (skill name → "Run the
   X skill" template; prompt template → ``{{ payload }}``
   substituted), run to completion, capture
   ``last_assistant_message``.

2. **Deliver**: route the response per ``sub.delivery_target``:

   - ``log`` — INFO log via ``logging``.
   - ``file:<path>`` — append to ``<path>`` with timestamp delimiter.
   - ``gateway://<platform>/<chat_id>`` — find the running gateway
     daemon's adapter for ``<platform>`` and call ``send_text``.
   - ``none`` — fire-and-forget; agent's response is discarded.

The Agent runs in a worker thread (``asyncio.to_thread``) because
``Agent.run_until_done`` is synchronous. Same pattern the gateway's
``_process_message_background`` uses. ``daemon`` (when present)
provides the gateway adapter lookup; tests pass ``None``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..gateway.daemon import GatewayDaemon
    from .subscription import WebhookSubscription

logger = logging.getLogger(__name__)


_GATEWAY_PREFIX = "gateway://"
_FILE_PREFIX = "file:"
_AGENT_MAX_ITERATIONS = 20


# Prompt template used when binding_type == "skill". Compact +
# explicit so the model knows which skill to run and where the
# payload came from. Skills receive the parsed body as a JSON code
# block plus the small forwarded-headers dict for context (X-GitHub-
# Event etc.).
_SKILL_PROMPT = """\
Run the `{skill_name}` skill on this webhook payload.

Headers:
```json
{headers_json}
```

Payload:
```json
{payload_json}
```"""


async def dispatch_webhook(
    daemon: GatewayDaemon | None,
    sub: WebhookSubscription,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    agent_factory=None,
) -> None:
    """Build prompt → run agent → route response.

    ``agent_factory`` is injected for tests; production passes
    ``None`` and we construct a fresh Agent against the active
    profile. The factory contract: ``() -> Agent``.

    Every failure path is caught and logged. A webhook firing is a
    background side-effect; an exception here should never propagate
    up the asyncio task chain and surface as an unhandled coroutine
    warning.
    """
    try:
        prompt = _build_prompt(sub, payload, headers)
    except Exception:
        logger.exception(
            "webhook %s: failed to build prompt",
            sub.id,
        )
        return

    try:
        response = await _run_agent(sub, prompt, agent_factory=agent_factory)
    except Exception:
        logger.exception(
            "webhook %s: agent run failed",
            sub.id,
        )
        return

    try:
        await _deliver(daemon, sub, response)
    except Exception:
        logger.exception(
            "webhook %s: delivery failed for target %s",
            sub.id,
            sub.delivery_target,
        )


# ---- prompt construction -------------------------------------------


def _build_prompt(
    sub: WebhookSubscription,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> str:
    """Skill binding → _SKILL_PROMPT; prompt template → substituted."""
    payload_json = json.dumps(payload, indent=2, default=str)
    headers_json = json.dumps(headers, indent=2)

    if sub.binding_type == "skill":
        if not sub.skill_name:
            raise ValueError(f"webhook {sub.id}: binding_type='skill' but no skill_name")
        return _SKILL_PROMPT.format(
            skill_name=sub.skill_name,
            headers_json=headers_json,
            payload_json=payload_json,
        )

    if sub.binding_type == "prompt":
        template = sub.prompt_template or ""
        if not template:
            raise ValueError(f"webhook {sub.id}: binding_type='prompt' but no template")
        return _substitute_template(template, payload, headers)

    raise ValueError(f"webhook {sub.id}: unknown binding_type {sub.binding_type!r}")


def _substitute_template(
    template: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> str:
    """Replace ``{{ payload }}`` and ``{{ headers }}`` placeholders.

    Tolerant of optional whitespace inside the braces. Anything else
    in the template (literal ``{{`` not part of a known placeholder)
    passes through untouched.
    """
    payload_json = json.dumps(payload, indent=2, default=str)
    headers_json = json.dumps(headers, indent=2)
    out = template
    for variants in (
        ("{{ payload }}", "{{payload}}", "{{  payload  }}"),
        ("{{ headers }}", "{{headers}}", "{{  headers  }}"),
    ):
        for v in variants:
            if v in out:
                replacement = payload_json if "payload" in v else headers_json
                out = out.replace(v, replacement)
    return out


# ---- agent run ----------------------------------------------------


async def _run_agent(
    sub: WebhookSubscription,
    prompt: str,
    *,
    agent_factory=None,
) -> str:
    """Construct an Agent, run one turn, return last assistant
    message. Agent runs in a worker thread; the asyncio loop stays
    free.

    The worker installs ``AUTO_DENY`` and ``write_origin=SYSTEM``
    inside the worker thread itself. A webhook daemon has no stdin
    bound so any confirmation prompt would block the executor
    forever, and without an explicit write_origin every webhook
    mutation was being attributed to ``foreground`` — the curator
    then refused to prune them.
    """
    from ..provenance import SYSTEM
    from ..safety.thread_entry import non_foreground_thread

    if agent_factory is None:
        agent_factory = _default_agent_factory
    agent = await asyncio.to_thread(agent_factory)

    def _run_with_guards() -> None:
        # write-origin=SYSTEM + AUTO_DENY + fresh approval scope. A
        # webhook daemon has no stdin, so any confirmation prompt would
        # block the executor forever; SYSTEM keeps the curator from
        # treating webhook mutations as foreground.
        with non_foreground_thread(origin=SYSTEM):
            agent.run_until_done(prompt, max_iterations=_AGENT_MAX_ITERATIONS)

    try:
        await asyncio.to_thread(_run_with_guards)
        return agent.last_assistant_message() or ""
    finally:
        close = getattr(agent, "close", None)
        if close is not None:
            try:
                await asyncio.to_thread(close)
            except Exception:
                logger.debug(
                    "webhook %s: agent.close raised",
                    sub.id,
                    exc_info=True,
                )


def _default_agent_factory():
    """Production factory: load current config + workspace, build a
    fresh Agent. One per webhook fire — webhooks are stateless."""
    from ..agent.core import Agent
    from ..config import load_config
    from ..profiles.resolution import resolve_active_profile

    cfg = load_config()
    cfg.profile = resolve_active_profile(config_default=cfg.profile)
    workspace = Path.cwd()
    return Agent(cfg, workspace, model=cfg.model)


# ---- delivery routing --------------------------------------------


def _parse_gateway_target(target: str) -> tuple[str, str] | None:
    """``gateway://<platform>/<chat_id>`` → ``(platform, chat_id)``."""
    if not target.startswith(_GATEWAY_PREFIX):
        return None
    rest = target[len(_GATEWAY_PREFIX) :]
    if "/" not in rest:
        return None
    platform, chat_id = rest.split("/", 1)
    if not platform or not chat_id:
        return None
    return platform, chat_id


async def _deliver(
    daemon: GatewayDaemon | None,
    sub: WebhookSubscription,
    response: str,
) -> None:
    """Route ``response`` per ``sub.delivery_target``."""
    target = (sub.delivery_target or "log").strip()

    if target == "log" or not response:
        logger.info(
            "webhook %s response: %s",
            sub.id,
            (response or "(empty)")[:500],
        )
        return

    if target == "none":
        return

    if target.startswith(_FILE_PREFIX):
        await _deliver_file(sub, response, target[len(_FILE_PREFIX) :])
        return

    if target.startswith(_GATEWAY_PREFIX):
        await _deliver_gateway(daemon, sub, response, target)
        return

    logger.warning(
        "webhook %s: unknown delivery_target %r — falling back to log",
        sub.id,
        target,
    )
    logger.info("webhook %s response: %s", sub.id, response[:500])


async def _deliver_file(
    sub: WebhookSubscription,
    response: str,
    path_str: str,
) -> None:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    delimiter = f"\n--- webhook {sub.id} {timestamp} ---\n"
    # Use asyncio.to_thread for the actual write so we don't block
    # the loop on disk I/O.
    await asyncio.to_thread(
        _append_text,
        path,
        delimiter + response + "\n",
    )


def _append_text(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


async def _deliver_gateway(
    daemon: GatewayDaemon | None,
    sub: WebhookSubscription,
    response: str,
    target: str,
) -> None:
    parsed = _parse_gateway_target(target)
    if parsed is None:
        logger.warning(
            "webhook %s: malformed gateway target %r",
            sub.id,
            target,
        )
        return
    platform, chat_id = parsed

    if daemon is None:
        logger.warning(
            "webhook %s: gateway target %s but no daemon attached "
            "(running outside `athena gateway run`?)",
            sub.id,
            target,
        )
        return

    adapter = daemon.adapter_for(platform)
    if adapter is None:
        logger.warning(
            "webhook %s: no %r adapter registered on the gateway",
            sub.id,
            platform,
        )
        return

    try:
        await adapter.send_text(chat_id, response)
    except Exception:
        logger.exception(
            "webhook %s: gateway send to %s failed",
            sub.id,
            target,
        )
