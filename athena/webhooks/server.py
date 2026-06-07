"""Webhook HTTP listener (aiohttp).

Binds inside the gateway daemon. Single route:
``POST /webhook/<webhook_id>``. Each inbound request flows through:

1. **Lookup** — pull the :class:`WebhookSubscription` from
   :class:`WebhookStore`. Unknown id or disabled subscription
   ⇒ 404.
2. **Authenticate** — HMAC-SHA256, Bearer, or none, per
   ``sub.auth_type``. Failure ⇒ 401.
3. **Idempotency** — if the sender supplied
   ``X-Webhook-Idempotency-Key``, the cache short-circuits
   duplicates within :data:`IdempotencyCache.ttl_seconds` to
   ``200 OK no-op`` so retrying senders don't fire the agent twice.
4. **Rate limit** — sliding 60s window per webhook. Over-budget
   ⇒ 429.
5. **Dispatch** — JSON-decode the body (falling back to a base64
   wrapper for binary), spawn the actual agent run as a background
   task via ``asyncio.create_task``, return ``202 Accepted``
   immediately so the upstream service doesn't time out waiting on
   us.

The dispatch callback is injected at construction
(:class:`WebhookServer(daemon, store, dispatch=...)`) so this
module doesn't pull in :mod:`.delivery` at import time. Phase 15.3
wires the real callback; tests stub it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from aiohttp import web

from .auth import verify_bearer, verify_hmac_sha256
from .idempotency import IdempotencyCache
from .rate_limit import RateLimiter
from .subscription import WebhookStore, WebhookSubscription

if TYPE_CHECKING:
    from ..gateway.daemon import GatewayDaemon


logger = logging.getLogger(__name__)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4747


DispatchFn = Callable[
    [WebhookSubscription, dict[str, Any], dict[str, str]],
    Awaitable[None],
]


async def _noop_dispatch(
    _sub: WebhookSubscription,
    _payload: dict[str, Any],
    _headers: dict[str, Any],
) -> None:
    """Placeholder dispatch used by tests that only care about the
    HTTP-layer behavior. Production wires this to
    :func:`athena.webhooks.delivery.dispatch_webhook`."""
    return None


class WebhookServer:
    """aiohttp-backed listener bound to ``host:port``.

    Lifecycle mirrors the gateway adapters: :meth:`start` brings up
    the server, :meth:`stop` tears it down. The gateway daemon
    bookends both around its own start/stop in Phase 15.4.
    """

    def __init__(
        self,
        daemon: GatewayDaemon | None,
        store: WebhookStore,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        dispatch: DispatchFn | None = None,
        idempotency_ttl: float = 600.0,
    ) -> None:
        self.daemon = daemon
        self.store = store
        self.host = host
        self.port = port
        self.dispatch: DispatchFn = dispatch or _noop_dispatch
        self.idempotency = IdempotencyCache(ttl_seconds=idempotency_ttl)
        self.rate_limiter = RateLimiter()

        self.app = web.Application()
        self.app.router.add_post(
            "/webhook/{webhook_id}",
            self._handle,
        )
        # Health endpoint — operators want to verify the listener
        # bound correctly without firing a real webhook.
        self.app.router.add_get("/health", self._health)

        self._runner: web.AppRunner | None = None
        self._site: web.BaseSite | None = None
        # Tasks spawned by the handler; cancelled on shutdown so a
        # slow agent run can't keep the process alive past stop.
        self._dispatch_tasks: set[asyncio.Task[Any]] = set()
        # Set to True the moment ``stop()`` begins. ``_handle``
        # checks this BEFORE spawning a new dispatch task so a
        # request that lands during the shutdown window doesn't
        # get added to ``_dispatch_tasks`` after we've already
        # cleared the set and gathered the cancellations.
        self._stopping = False

    # ---- lifecycle ----

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(
            "webhook server listening on http://%s:%d",
            self.host,
            self.port,
        )

    async def stop(self) -> None:
        if self._runner is None:
            return
        # Latch the stopping flag BEFORE we snapshot the dispatch set
        # so a request arriving in the next few microseconds will see
        # ``_stopping == True`` in _handle and 503 immediately
        # without adding itself to the set we're about to drain.
        self._stopping = True
        # Cancel in-flight dispatches first so they don't outlive
        # the listener's HTTP context (we already 202-acked the
        # caller; nothing's waiting for the agent's reply over HTTP).
        tasks = list(self._dispatch_tasks)
        self._dispatch_tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self._runner.cleanup()
        finally:
            self._runner = None
            self._site = None

    # ---- request handlers ----

    async def _health(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "webhooks": len(self.store.list()),
            }
        )

    async def _handle(self, request: web.Request) -> web.Response:
        # Reject requests that arrive during the shutdown window so
        # they don't get added to _dispatch_tasks after we've drained
        # it. Without this, the set.add can run between stop()'s
        # clear() and gather(), leaving an orphan task that survives
        # the listener teardown.
        if self._stopping:
            return web.Response(status=503, text="server shutting down")

        webhook_id = request.match_info["webhook_id"]
        sub = self.store.get(webhook_id)
        if sub is None:
            return web.Response(status=404, text="webhook not found")
        if not sub.enabled:
            return web.Response(status=404, text="webhook disabled")

        body = await request.read()

        # 1. Authenticate. Auth failures are a security event --
        # WARNING level so they're picked up by log aggregation /
        # alert rules. INFO was too quiet for the post-incident
        # search you'd run after a credential leak.
        if not self._authenticate(sub, request, body):
            logger.warning("[%s] auth failed", webhook_id)
            return web.Response(status=401, text="authentication failed")

        # 2. Idempotency check (only when sender supplies the header).
        idem_key = request.headers.get("X-Webhook-Idempotency-Key")
        if idem_key and not self.idempotency.check_and_record(
            webhook_id,
            idem_key,
        ):
            logger.debug(
                "[%s] idempotency duplicate (key=%s)",
                webhook_id,
                idem_key,
            )
            return web.Response(
                status=200,
                text="duplicate; no-op",
            )

        # 3. Rate limit.
        if not self.rate_limiter.check(
            webhook_id,
            sub.rate_limit_per_minute,
        ):
            logger.warning(
                "[%s] rate-limited (per_minute=%d)",
                webhook_id,
                sub.rate_limit_per_minute,
            )
            return web.Response(status=429, text="rate limited")

        # 4. Parse body. Non-JSON gets a clear wrapper so the agent
        #    can still see the bytes without us pretending it's text.
        payload = _parse_body(body)

        # 5. Snapshot headers we want to expose to the dispatch
        #    callback (some skills key off X-GitHub-Event etc.).
        forwarded_headers = _snapshot_headers(request.headers)

        # 6. Async dispatch — caller gets 202 immediately.
        task = asyncio.create_task(
            self._safe_dispatch(sub, payload, forwarded_headers),
            name=f"webhook-dispatch-{webhook_id[:8]}",
        )
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)

        self.store.record_fire(sub.id)
        return web.Response(status=202, text="accepted")

    # ---- helpers ----

    def _authenticate(
        self,
        sub: WebhookSubscription,
        request: web.Request,
        body: bytes,
    ) -> bool:
        if sub.auth_type == "none":
            return True
        if sub.auth_type == "hmac_sha256":
            sig = (
                request.headers.get("X-Webhook-Signature")
                or request.headers.get("X-Hub-Signature-256")
                or ""
            )
            return verify_hmac_sha256(body, sig, sub.auth_secret)
        if sub.auth_type == "bearer":
            return verify_bearer(
                request.headers.get("Authorization", ""),
                sub.auth_secret,
            )
        return False

    async def _safe_dispatch(
        self,
        sub: WebhookSubscription,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        try:
            await self.dispatch(sub, payload, headers)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "webhook dispatch failed for %s",
                sub.id,
            )


# ---- module-level helpers (testable in isolation) ---------------------


def _parse_body(body: bytes) -> dict[str, Any]:
    """Decode the request body to a payload dict.

    Tries JSON first; non-JSON falls back to ``{"_raw_body_base64":
    ..., "_content_type_hint": ...}`` so the agent can still see
    the bytes. A skill that wants the raw body decodes the base64
    itself.
    """
    if not body:
        return {}
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return {"_raw_body_base64": base64.b64encode(body).decode("ascii")}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {
            "_raw_body": text,
            "_format_hint": "non-json plaintext",
        }
    if isinstance(parsed, dict):
        return parsed
    # Top-level non-object JSON (array, string, number) — wrap so the
    # callback signature stays predictable. Surface a warning so the
    # operator notices: skills written against a schema that expects
    # a top-level array (some GitHub events do this) will silently
    # fail their schema check against the wrapper. The warning lets
    # them see the mismatch in logs without having to instrument the
    # callback.
    logger.warning(
        "webhook payload is a top-level %s; wrapping as "
        "{'_top_level': ...}. Skills expecting the raw array/scalar "
        "must read payload['_top_level'].",
        type(parsed).__name__,
    )
    return {"_top_level": parsed}


_FORWARDED_HEADER_PREFIXES: tuple[str, ...] = (
    "x-github-",
    "x-gitlab-",
    "x-bitbucket-",
    "x-linear-",
    "x-circleci-",
    "x-event-",
    "user-agent",
)


def _snapshot_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Filter the request headers to a small set the agent might
    care about (event type, source identity, etc.).

    We don't forward Authorization / X-Webhook-Signature — those
    are auth metadata, not application data, and leaking them to the
    agent's prompt is unnecessary.

    Header values are deduplicated correctly: aiohttp's
    ``CIMultiDict`` is multi-valued (a webhook source legitimately
    can -- and GitHub sometimes does -- send the same header twice).
    ``headers.items()`` yields each occurrence separately, which
    would overwrite the first with the last on ``out[key] = value``.
    We use ``getall`` and join with ``", "`` (the standard
    HTTP repeatable-header concatenation) so the skill sees every
    value the sender supplied.
    """
    out: dict[str, str] = {}
    # Pull unique lowercase keys first, then collapse each key's
    # values via getall(). The seen set guards against doing the
    # work twice when a key occurs N times.
    seen: set[str] = set()
    for key in headers.keys():
        lower = key.lower()
        if lower in seen:
            continue
        seen.add(lower)
        if lower in ("authorization", "x-webhook-signature", "x-hub-signature-256"):
            continue
        if not (
            lower.startswith(_FORWARDED_HEADER_PREFIXES)
            or lower == "content-type"
            or lower == "x-webhook-idempotency-key"
        ):
            continue
        # getall is the CIMultiDict accessor that returns every value
        # for the key. Fall back to a single-value get for plain dict
        # inputs (unit tests can pass a dict directly).
        getall = getattr(headers, "getall", None)
        if getall is not None:
            values = list(getall(key))
        else:
            values = [headers[key]]
        # ", " join is the RFC-7230 standard for repeating
        # headers; a downstream skill that wants to split is free to
        # do so. A single value pre-serializes identically.
        out[key] = ", ".join(values)
    return out
