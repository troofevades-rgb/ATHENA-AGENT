"""HTTP/SSE MCP transport.

The MCP spec defines two transports: stdio (Phase 0 carryover) and
HTTP+SSE. Most hosted MCP servers (Linear, Atlassian, Sentry,
Smithery-routed servers, etc.) only support the HTTP path because
they can't ship a binary to your machine.

Wire protocol (legacy MCP SSE shape — the one most servers
currently implement):

- Client opens ``GET /sse`` with ``Authorization: Bearer <token>`` and
  ``Accept: text/event-stream``.
- Server's first SSE event is an ``endpoint`` event whose ``data:``
  is the POST URL for future requests, e.g.
  ``/messages?sessionId=abc123``.
- Client POSTs JSON-RPC requests to that endpoint with the bearer
  header.
- Server pushes responses (and server-initiated notifications) back
  over the SSE stream as JSON-RPC messages, one per event.

Sync façade:

The rest of athena's MCP code is synchronous (athena/mcp/client.py
runs on the agent's worker thread). To preserve that, this transport
runs its event loop in a background daemon thread and exposes
synchronous methods that bridge into it via
``asyncio.run_coroutine_threadsafe``. The public API mirrors
:class:`~athena.mcp.client.MCPStdioClient` so the resolver can hand
either to callers without them needing to care which transport ran.

OAuth integration: when an ``oauth_cfg`` is supplied, the transport
loads the persisted token at construction, refreshes it
proactively if within :data:`needs_refresh` window, and re-runs
:func:`run_authorization_flow` if no token exists. A 401 mid-stream
triggers a refresh-and-reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutTimeout
from typing import Any

import httpx

from . import oauth as oauth_mod

logger = logging.getLogger(__name__)


PROTOCOL_VERSION = "2024-11-05"

_DEFAULT_POST_ENDPOINT = "/messages"
_RECONNECT_BASE = 1.0
_RECONNECT_MAX = 30.0
_OPEN_TIMEOUT = 30.0
_REQUEST_TIMEOUT = 60.0


class SSEError(RuntimeError):
    """Anything that went wrong on the SSE wire."""


class SSETransport:
    """Synchronous façade over an async SSE/POST MCP transport.

    Lifecycle:

    - Construction kicks the background loop thread, refreshes the
      OAuth token if applicable, opens the SSE stream, waits for the
      ``endpoint`` event (or times out), and returns.
    - :meth:`initialize` / :meth:`list_tools` / :meth:`call_tool`
      send JSON-RPC requests and wait for the matching response.
    - :meth:`close` cancels the loop and joins the thread.
    """

    name: str

    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        oauth_cfg: oauth_mod.OAuthConfig | None = None,
        request_timeout: float = _REQUEST_TIMEOUT,
        open_timeout: float = _OPEN_TIMEOUT,
    ) -> None:
        self.name = name
        if not base_url:
            raise ValueError("base_url must be non-empty")
        self.base_url = base_url.rstrip("/")
        self.oauth_cfg = oauth_cfg
        self.request_timeout = request_timeout
        self.open_timeout = open_timeout

        # Public state (read-only outside the class).
        self._tools_cache: list[dict[str, Any]] | None = None
        self.stderr_buffer: list[str] = []  # diagnostic ring buffer
        # initialize() result, kept for /mcp listing parity with stdio.
        self._server_info: dict[str, Any] = {}
        # ID counter (incremented inside the loop thread, but reads
        # from the sync side are fine because it's only used in
        # _next_request_id which itself runs in the loop).
        self._id_counter = 0

        # Loop-thread state. These attributes are accessed by both
        # the loop thread and the public sync methods; the loop is
        # a daemon thread, and we coordinate via run_coroutine_threadsafe.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._endpoint_ready = threading.Event()
        self._closed = False

        # Async-side state — only mutated from the loop thread.
        self._client: httpx.AsyncClient | None = None
        self._stream_task: asyncio.Task | None = None
        self._post_endpoint: str = _DEFAULT_POST_ENDPOINT
        self._pending: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._token: oauth_mod.StoredToken | None = None

        # Start the loop thread and run the opening dance.
        self._spawn_loop_thread()
        try:
            self._loop_ready.wait(timeout=5.0)
            if self._loop is None:
                raise SSEError("event loop failed to start")
            self._submit_blocking(
                self._async_open(),
                timeout=self.open_timeout,
            )
        except BaseException:
            # Tear down the loop on any failure so we don't leak the thread.
            self.close()
            raise

    # ---- loop thread ----

    def _spawn_loop_thread(self) -> None:
        def _runner() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self._loop_ready.set()
            try:
                loop.run_forever()
            finally:
                try:
                    pending = asyncio.all_tasks(loop=loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                loop.close()

        self._thread = threading.Thread(
            target=_runner,
            name=f"mcp-sse-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def _submit_blocking(self, coro, *, timeout: float | None = None) -> Any:
        assert self._loop is not None, "loop not started"
        cf: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return cf.result(timeout=timeout)
        except FutTimeout as e:
            cf.cancel()
            raise SSEError(f"MCP SSE request timed out after {timeout}s") from e

    # ---- async open ----

    async def _async_open(self) -> None:
        # Refresh-or-acquire OAuth token if applicable.
        if self.oauth_cfg is not None:
            await self._ensure_token()
        headers = self._auth_headers()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0),
        )
        # Kick the listener and wait for the endpoint event.
        self._stream_task = asyncio.create_task(self._listen())
        # Poll the endpoint-ready flag — the listener sets it as soon
        # as it receives the first `event: endpoint` event. Use a
        # short bounded wait so a server that doesn't issue endpoint
        # events (rare) doesn't hang us indefinitely.
        deadline = asyncio.get_event_loop().time() + self.open_timeout
        while not self._endpoint_ready.is_set():
            if asyncio.get_event_loop().time() > deadline:
                # No endpoint event — fall back to the default. Most
                # legacy servers conform to /messages without sending
                # an endpoint event at all.
                self._endpoint_ready.set()
                break
            await asyncio.sleep(0.05)

    async def _ensure_token(self) -> None:
        if self.oauth_cfg is None:
            return
        token = oauth_mod.load_token(self.oauth_cfg.server_id)
        if token is None:
            token = await oauth_mod.run_authorization_flow_async(
                self.oauth_cfg,
            )
            oauth_mod.save_token(self.oauth_cfg.server_id, token)
        elif token.needs_refresh:
            try:
                token = await oauth_mod.refresh_async(self.oauth_cfg, token)
                oauth_mod.save_token(self.oauth_cfg.server_id, token)
            except oauth_mod.OAuthError:
                logger.warning(
                    "[%s] refresh failed; re-running authorization flow",
                    self.name,
                )
                token = await oauth_mod.run_authorization_flow_async(
                    self.oauth_cfg,
                )
                oauth_mod.save_token(self.oauth_cfg.server_id, token)
        self._token = token

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "text/event-stream, application/json"}
        if self._token is not None:
            headers["Authorization"] = f"{self._token.token_type} {self._token.access_token}"
        return headers

    # ---- SSE listener ----

    async def _listen(self) -> None:
        """Long-running task that reads SSE events and dispatches
        them.

        Reconnects with exponential backoff on stream failure. A 401
        triggers a token refresh before the next attempt — handles the
        "token revoked / rotated by another client" case.
        """
        backoff = _RECONNECT_BASE
        while not self._closed:
            # Clear the endpoint-ready flag before each connect
            # attempt so callers that arrive during the reconnect
            # window are forced to wait for the new server's
            # ``endpoint`` event rather than posting to a stale
            # session URL from the prior connection. ``_post_endpoint``
            # is overwritten as soon as the new endpoint frame
            # arrives (see _handle_frame).
            self._endpoint_ready.clear()
            try:
                async with self._client.stream("GET", "/sse") as r:
                    if r.status_code == 401 and self.oauth_cfg is not None:
                        logger.info(
                            "[%s] 401 on SSE connect; refreshing token",
                            self.name,
                        )
                        await self._ensure_token()
                        # Rebuild client with new headers.
                        await self._client.aclose()
                        self._client = httpx.AsyncClient(
                            base_url=self.base_url,
                            headers=self._auth_headers(),
                            timeout=httpx.Timeout(
                                connect=10.0,
                                read=None,
                                write=30.0,
                                pool=30.0,
                            ),
                        )
                        continue
                    r.raise_for_status()
                    backoff = _RECONNECT_BASE
                    await self._read_events(r)
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._closed:
                    break
                logger.warning(
                    "[%s] SSE stream lost; backoff %.1fs",
                    self.name,
                    backoff,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX)

    async def _read_events(self, response: httpx.Response) -> None:
        """Parse SSE frames out of the stream.

        Each frame is a sequence of ``key: value`` lines terminated
        by a blank line. ``data:`` lines accumulate; ``event:`` sets
        the event type. We care about two event types:

        - ``endpoint`` (or first-event-with-data-looking-like-a-URL):
          sets :attr:`_post_endpoint` and trips
          :attr:`_endpoint_ready`.
        - ``message`` (or unset / "data"): JSON-RPC message; dispatch
          to the pending future or treat as a notification.
        """
        event_type = "message"
        data_buf: list[str] = []
        async for line in response.aiter_lines():
            if line == "":
                # End of frame.
                if data_buf:
                    self._handle_frame(event_type, "\n".join(data_buf))
                event_type = "message"
                data_buf = []
                continue
            if line.startswith(":"):
                # SSE comment / keepalive.
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            value = value.lstrip(" ")
            if key == "event":
                event_type = value
            elif key == "data":
                data_buf.append(value)

    def _handle_frame(self, event_type: str, data: str) -> None:
        if event_type == "endpoint":
            # The data is a URL — could be relative or absolute.
            self._post_endpoint = data.strip() or _DEFAULT_POST_ENDPOINT
            self._endpoint_ready.set()
            logger.info(
                "[%s] received endpoint %s",
                self.name,
                self._post_endpoint,
            )
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("[%s] non-JSON SSE frame dropped: %r", self.name, data[:100])
            return
        # Drop our message-id key for the pending lookup.
        msg_id = payload.get("id")
        if msg_id is not None and msg_id in self._pending:
            fut = self._pending.pop(msg_id)
            if not fut.done():
                fut.set_result(payload)
            return
        # Server-initiated notification — log; nothing currently
        # subscribes. Future work: route to a callback.
        logger.debug(
            "[%s] notification: %s",
            self.name,
            payload.get("method") or "?",
        )

    # ---- public sync API ----

    def initialize(self) -> dict[str, Any]:
        """JSON-RPC initialize handshake. Mirrors the stdio shape."""
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "athena",
                    "version": "0.2.0",
                },
            },
        )
        # Mirror MCPStdioClient: cache the initialize response so the
        # /mcp slash command can show server name + version without
        # re-issuing the handshake. The stdio attribute is named
        # ``_server_info``; keep the name aligned so the command's
        # shared accessor works against either transport.
        self._server_info = result if isinstance(result, dict) else {}
        return result

    def list_tools(self, refresh: bool = False) -> list[dict[str, Any]]:
        if not refresh and self._tools_cache is not None:
            return self._tools_cache
        result = self.request("tools/list")
        tools = result.get("tools") or []
        self._tools_cache = list(tools) if isinstance(tools, list) else []
        return self._tools_cache

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise SSEError(f"[{self.name}] transport is closed")
        timeout = timeout if timeout is not None else self.request_timeout
        # Poll incrementally so that if the server connection drops
        # mid-request (e.g. token revoked, network blip), the caller
        # unblocks in ~1s instead of stalling for the full
        # request_timeout (60s default). Mirrors the dead-server check
        # MCPStdioClient.request added; without it, every foreground
        # tool call against a wedged SSE server stalled a full minute
        # while ``_listen`` was already trying to reconnect.
        coro_future = asyncio.run_coroutine_threadsafe(
            self._async_request(method, params), self._loop
        ) if self._loop is not None else None
        if coro_future is None:
            raise SSEError(f"[{self.name}] event loop unavailable")
        elapsed = 0.0
        step = 1.0
        while True:
            remaining = timeout - elapsed
            if remaining <= 0:
                coro_future.cancel()
                raise SSEError(f"[{self.name}] timeout waiting for {method!r}")
            try:
                result_box = coro_future.result(timeout=min(step, remaining))
                break
            except FutTimeout:
                if not self.is_alive():
                    coro_future.cancel()
                    raise SSEError(
                        f"[{self.name}] transport closed while waiting for {method!r}"
                    )
                elapsed += step
        if "error" in result_box:
            err = result_box["error"]
            raise SSEError(f"[{self.name}] {method} returned error: {err}")
        return result_box.get("result") or {}

    async def _async_request(
        self,
        method: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        # Wait for the endpoint event (or its default fallback) to
        # be ready before posting. ``_open`` already does this, but a
        # reconnect can clear the readiness — be defensive.
        if not self._endpoint_ready.is_set():
            await asyncio.sleep(0.05)

        self._id_counter += 1
        msg_id = self._id_counter
        envelope = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {},
        }
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        try:
            r = await self._client.post(
                self._post_endpoint,
                json=envelope,
            )
            if r.status_code == 401 and self.oauth_cfg is not None:
                logger.info(
                    "[%s] 401 on POST %s; refreshing token",
                    self.name,
                    method,
                )
                await self._ensure_token()
                # Update the client headers in place.
                self._client.headers.update(self._auth_headers())
                r = await self._client.post(
                    self._post_endpoint,
                    json=envelope,
                )
            if r.status_code >= 400:
                self._pending.pop(msg_id, None)
                raise SSEError(
                    f"POST {self._post_endpoint} returned {r.status_code}: {(r.text or '')[:500]}"
                )
        except SSEError:
            raise
        except Exception as e:
            self._pending.pop(msg_id, None)
            raise SSEError(f"POST failed: {e}") from e

        return await future

    # --- parity shims with MCPStdioClient so /mcp and the dead-server
    # detection in MCPStdioClient.request can poll the same attributes
    # / methods regardless of transport.

    @property
    def _tools(self) -> list[dict[str, Any]] | None:
        """Alias of ``_tools_cache`` matching the stdio client's
        attribute name so ``/mcp`` can read tool counts uniformly."""
        return self._tools_cache

    def is_alive(self) -> bool:
        """True while the SSE transport is still serving requests.
        Mirrors :meth:`MCPStdioClient.is_alive`. The transport is
        considered dead once :meth:`close` has been called."""
        return not self._closed

    def stderr_tail(self, n: int = 50) -> list[str]:
        """Last ``n`` lines from the diagnostic ring buffer. Mirrors
        :meth:`MCPStdioClient.stderr_tail` so ``/mcp logs NAME``
        works for both transports."""
        if n <= 0:
            return []
        return list(self.stderr_buffer[-n:])

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                cf = asyncio.run_coroutine_threadsafe(
                    self._async_close(),
                    loop,
                )
                try:
                    cf.result(timeout=5.0)
                except Exception:
                    cf.cancel()
            finally:
                loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    async def _async_close(self) -> None:
        if self._stream_task is not None and not self._stream_task.done():
            self._stream_task.cancel()
            try:
                await self._stream_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(SSEError("transport closed"))
        self._pending.clear()
