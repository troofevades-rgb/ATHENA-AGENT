"""aiohttp-backed OpenAI-compatible proxy server (T3-01R.3).

Routes:
- ``POST /v1/chat/completions`` — accept an OpenAI request, route
  via :func:`athena.proxy.router.route_request`, build a
  :class:`Provider` via the existing ``_build_provider`` path,
  stream the result through :mod:`athena.proxy.translate`. Honors
  the ``stream`` flag.
- ``GET  /v1/models`` — union of every available provider's
  ``list_models()`` in OpenAI-list shape.
- ``POST /v1/embeddings`` — stubbed 501.
- ``GET  /health`` — operator probe.

Sits on the same aiohttp stack the webhook listener uses
(``athena/webhooks/server.py``), so a single server family covers
all athena-as-server roles. Each request gets a Phase-16
observability span via
:func:`athena.plugins.bundled.observability.spans.start_span` —
inert when the ``[observability]`` extra is missing.

Sync provider iteration runs in a threadpool
(``asyncio.to_thread``) so it doesn't block the aiohttp event
loop; the translation generator is pumped on the loop side and
each SSE chunk is written to the response as it lands.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from ..plugins.bundled.observability.spans import start_span
from ..providers.base import Provider, StreamChunk
from .logging import ProxyLogger
from .router import RouteError, route_request
from .translate import (
    collect_chunks_to_openai_response,
    stream_chunks_to_openai_sse,
)

if TYPE_CHECKING:
    from ..config import Config
    from ..providers.credential_pool import CredentialPool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def make_app(
    *,
    cfg: Config,
    pool: CredentialPool,
    provider_factory: Callable[[str, str], tuple[Provider, str]] | None = None,
) -> web.Application:
    """Build the aiohttp :class:`web.Application`.

    ``provider_factory`` is ``(provider_name, requested_model) ->
    (Provider, resolved_model)``. Defaults to a closure over
    :func:`athena.providers.runtime_resolver._build_provider`. Tests
    inject a stub so the suite stays hermetic.
    """
    from ..providers import list_providers as registered_providers
    from ..providers.runtime_resolver import _build_provider as _runtime_build

    if provider_factory is None:

        def _default_factory(name: str, model: str) -> tuple[Provider, str]:
            return _runtime_build(name, model, cfg, pool)

        provider_factory = _default_factory

    proxy_log = ProxyLogger(
        log_path=Path(cfg.proxy_log_path).expanduser(),
        bodies_dir=Path(cfg.proxy_bodies_dir).expanduser(),
        log_bodies=cfg.proxy_log_bodies,
    )

    def _available_providers() -> list[str]:
        registered = set(registered_providers())
        with_creds = set(pool.providers())
        out: set[str] = set(with_creds)
        if "ollama" in registered:
            out.add("ollama")
        return sorted(out)

    # ---- handlers ------------------------------------------------------

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "providers": _available_providers()})

    async def list_models(_request: web.Request) -> web.Response:
        data: list[dict[str, Any]] = []
        for provider_name in _available_providers():
            try:
                provider, _ = provider_factory(provider_name, "")
            except Exception as e:  # noqa: BLE001
                logger.debug("skipping %s in /v1/models: %s", provider_name, e)
                continue
            try:
                models = await asyncio.to_thread(provider.list_models)
            except Exception as e:  # noqa: BLE001
                logger.info("/v1/models: %s list_models() failed: %s", provider_name, e)
                models = []
            finally:
                try:
                    provider.close()
                except Exception:
                    pass
            for m in models:
                data.append(
                    {
                        "id": m,
                        "object": "model",
                        "created": 0,
                        "owned_by": provider_name,
                    }
                )
        return web.json_response({"object": "list", "data": data})

    async def embeddings_stub(_request: web.Request) -> web.Response:
        # 501 with an OpenAI-shaped error body so SDK clients render
        # the message sensibly.
        return web.json_response(
            {
                "error": {
                    "message": ("athena proxy does not implement /v1/embeddings yet."),
                    "type": "not_implemented",
                    "code": "embeddings_not_supported",
                }
            },
            status=501,
        )

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            return _openai_error(400, f"invalid JSON body: {e}", error_type="invalid_request_error")
        if not isinstance(body, dict):
            return _openai_error(400, "request body must be a JSON object")

        request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        client_ua = request.headers.get("User-Agent", "")
        provider_header = request.headers.get("X-Athena-Provider")
        requested_model = str(body.get("model") or "")
        stream = bool(body.get("stream", False))

        try:
            provider_name, _ = route_request(
                requested_model=requested_model,
                provider_header=provider_header,
                default_provider=cfg.proxy_default_provider,
                available_providers=_available_providers(),
            )
        except RouteError as e:
            return _openai_error(400, str(e), error_type="invalid_request_error")

        try:
            provider, resolved_model = await asyncio.to_thread(
                provider_factory, provider_name, requested_model
            )
        except RuntimeError as e:
            # resolve_provider raises RuntimeError when no credentials
            # are available — surface as an OpenAI-shaped 503.
            return _openai_error(
                503,
                str(e),
                error_type="provider_unavailable",
            )
        except Exception as e:  # noqa: BLE001
            return _openai_error(503, f"failed to build provider {provider_name!r}: {e}")

        stream_kwargs = _build_stream_kwargs(body, resolved_model)
        start = time.time()

        # Phase-16 observability span — inert without the
        # [observability] extra.
        span_attrs: dict[str, Any] = {
            "athena.proxy.provider": provider_name,
            "athena.proxy.model": resolved_model,
            "athena.proxy.requested_model": requested_model,
            "athena.proxy.stream": stream,
            "athena.proxy.client_ua": client_ua,
        }

        if stream:
            return await _stream_response(
                request=request,
                provider=provider,
                stream_kwargs=stream_kwargs,
                body=body,
                request_id=request_id,
                client_ua=client_ua,
                model_requested=requested_model,
                provider_used=provider_name,
                proxy_log=proxy_log,
                resolved_model=resolved_model,
                start=start,
                span_attrs=span_attrs,
            )

        # Non-streaming: drain the iterator into a single response.
        try:
            with start_span("athena.proxy.call", span_attrs) as span:
                chunks_iter = await asyncio.to_thread(provider.stream_chat, **stream_kwargs)
                response = await asyncio.to_thread(
                    collect_chunks_to_openai_response,
                    chunks_iter,
                    model=resolved_model,
                    request_id=request_id,
                )
                latency_ms = (time.time() - start) * 1000.0
                if span is not None:
                    usage = response.get("usage", {}) or {}
                    span.set_attribute(
                        "athena.proxy.tokens.prompt",
                        int(usage.get("prompt_tokens", 0)),
                    )
                    span.set_attribute(
                        "athena.proxy.tokens.completion",
                        int(usage.get("completion_tokens", 0)),
                    )
                    span.set_attribute("athena.proxy.latency_ms", round(latency_ms, 2))
        except Exception as e:  # noqa: BLE001
            try:
                provider.close()
            except Exception:
                pass
            return _openai_error(
                502,
                str(e),
                error_type="upstream_error",
            )

        try:
            provider.close()
        except Exception:
            pass

        usage = response.get("usage", {}) or {}
        proxy_log.log_completed(
            request_id=request_id,
            client_ua=client_ua,
            model_requested=requested_model,
            provider_used=provider_name,
            body=body,
            response=response,
            latency_ms=latency_ms,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
        )
        return web.json_response(response)

    # ---- app wiring ----------------------------------------------------

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/v1/models", list_models)
    app.router.add_post("/v1/chat/completions", chat_completions)
    app.router.add_post("/v1/embeddings", embeddings_stub)
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _openai_error(
    status: int,
    message: str,
    *,
    error_type: str = "server_error",
    code: str | None = None,
) -> web.Response:
    return web.json_response(
        {
            "error": {
                "message": message,
                "type": error_type,
                "code": code or error_type,
            }
        },
        status=status,
    )


def _build_stream_kwargs(body: dict[str, Any], resolved_model: str) -> dict[str, Any]:
    """Pull the kwargs accepted by :meth:`Provider.stream_chat` out of
    an incoming OpenAI request body. Unknown fields are dropped."""
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": body.get("messages") or [],
    }
    if body.get("tools"):
        kwargs["tools"] = body["tools"]
    if body.get("temperature") is not None:
        kwargs["temperature"] = float(body["temperature"])
    if body.get("max_tokens") is not None:
        kwargs["max_tokens"] = int(body["max_tokens"])
    return kwargs


async def _stream_response(
    *,
    request: web.Request,
    provider: Provider,
    stream_kwargs: dict[str, Any],
    body: dict[str, Any],
    request_id: str,
    client_ua: str,
    model_requested: str,
    provider_used: str,
    proxy_log: ProxyLogger,
    resolved_model: str,
    start: float,
    span_attrs: dict[str, Any],
) -> web.StreamResponse:
    """Stream SSE chunks out of the response.

    The provider's stream_chat returns a sync iterator; we pump it
    in a thread (one chunk at a time via a small queue) so the
    event loop stays responsive. The translate.py generator is
    driven on the loop side; usage callbacks accumulate into the
    proxy log scope.
    """
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    with start_span("athena.proxy.call", span_attrs) as span:
        with proxy_log.scope(
            request_id=request_id,
            client_ua=client_ua,
            model_requested=model_requested,
            provider_used=provider_used,
            body=body,
        ) as scope:
            tokens_seen: dict[str, int] = {"in": 0, "out": 0, "cache": 0}

            def _on_usage(p_in: int, p_out: int, p_cache: int) -> None:
                tokens_seen["in"] += p_in
                tokens_seen["out"] += p_out
                tokens_seen["cache"] += p_cache
                scope.add_tokens(in_=p_in, out=p_out, cache=p_cache)

            try:
                # Stream each SSE chunk to the client AS IT LANDS rather
                # than draining the whole generation first (which made
                # stream=true a lie — clients saw nothing until the
                # response was complete). The provider's stream_chat may
                # do blocking HTTP I/O on each ``next()``, so each step
                # runs in a worker thread; we AWAIT each before pulling
                # the next, so the generator is only ever touched by one
                # thread at a time (no concurrent-access hazard) and the
                # event loop is never blocked.
                chunks_iter: Iterator[StreamChunk] = provider.stream_chat(**stream_kwargs)
                sse_iter = stream_chunks_to_openai_sse(
                    chunks_iter,
                    model=resolved_model,
                    request_id=request_id,
                    on_usage=_on_usage,
                )

                _SENTINEL = object()

                def _next_sse() -> Any:
                    # StopIteration can't cross the thread/async boundary
                    # cleanly, so convert it to a sentinel here.
                    try:
                        return next(sse_iter)
                    except StopIteration:
                        return _SENTINEL

                while True:
                    sse_str = await asyncio.to_thread(_next_sse)
                    if sse_str is _SENTINEL:
                        break
                    await resp.write(sse_str.encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                logger.exception("proxy stream error")
                err_frame = _sse_error_frame(e)
                try:
                    await resp.write(err_frame.encode("utf-8"))
                    await resp.write(b"data: [DONE]\n\n")
                except Exception:
                    pass
            finally:
                latency_ms = (time.time() - start) * 1000.0
                scope.set_latency(time.time() - start)
                if span is not None:
                    span.set_attribute("athena.proxy.tokens.prompt", tokens_seen["in"])
                    span.set_attribute("athena.proxy.tokens.completion", tokens_seen["out"])
                    span.set_attribute("athena.proxy.latency_ms", round(latency_ms, 2))
                try:
                    provider.close()
                except Exception:
                    pass
                await resp.write_eof()
    return resp


def _sse_error_frame(exc: BaseException) -> str:
    payload = {
        "error": {
            "message": str(exc),
            "type": "stream_error",
            "code": type(exc).__name__,
        }
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
