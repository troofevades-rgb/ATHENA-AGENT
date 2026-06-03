"""ACP JSON-RPC 2.0 server over stdio.

Framing: every message is a single line of JSON on stdin / stdout.
Multi-line JSON values aren't used — the IDE writes one message per
``\\n``-terminated line, and we do the same on the way back. stderr is
free for diagnostic logging without interfering with the protocol.

Dispatch model:

- Methods (request/response): the client sends ``{"jsonrpc": "2.0",
  "id": N, "method": "...", "params": {...}}``. We call the
  registered handler; the handler's awaitable result becomes the
  JSON-RPC ``result`` field on the response, or an error object on
  exception.
- Notifications: ``{"jsonrpc": "2.0", "method": "...", "params": {...}}``
  with no ``id``. We call the registered handler and don't reply.
- Client-bound requests: we can send ``{"id": N, "method": ...}`` to
  the client (e.g. ``session/permission_request``). The client's
  response with matching ``id`` resolves the pending future
  registered at call time.

Concurrency: stdin is read serially but each dispatch is spawned as
its own task so a slow handler doesn't head-of-line block other
messages. stdout writes are serialized by an asyncio.Lock so two
notifications never interleave bytes on the wire.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


MethodHandler = Callable[[dict[str, Any]], Awaitable[Any]]
NotificationHandler = Callable[[dict[str, Any]], Awaitable[None]]


# JSON-RPC error codes (subset; per the spec).
ERR_PARSE = -32700
ERR_INVALID = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603


class ACPServer:
    """Stdio JSON-RPC server. One per IDE subprocess.

    Construct, register handlers via :meth:`method` / :meth:`notification`,
    then call :meth:`serve` to run the read-dispatch loop.
    """

    def __init__(
        self,
        *,
        stdin: asyncio.StreamReader | None = None,
        stdout=None,
    ) -> None:
        self._methods: dict[str, MethodHandler] = {}
        self._notifications: dict[str, NotificationHandler] = {}
        self._stdout_lock = asyncio.Lock()
        # Pre-set reader / writer for tests; production binds these
        # to real stdin / stdout in ``serve``.
        self._reader: asyncio.StreamReader | None = stdin
        self._writer = stdout if stdout is not None else sys.stdout

        self._pending_client_responses: dict[int | str, asyncio.Future[Any]] = {}
        self._client_request_id = 0
        # Tasks spawned by dispatch; cancelled at shutdown.
        self._tasks: set[asyncio.Task[Any]] = set()
        self._running = False
        # Latched True the moment shutdown begins. A request arriving
        # in the next few microseconds would otherwise spawn a task
        # that lands in ``_tasks`` AFTER ``_shutdown_tasks`` already
        # snapshot+cleared the set, orphaning it past the listener
        # teardown. Same race pattern as the webhook server fix
        # in commit 822d3a6.
        self._stopping = False

    # ---- registration ----

    def method(self, name: str):
        """Decorator: register an async handler for an inbound request."""

        def deco(fn: MethodHandler) -> MethodHandler:
            self._methods[name] = fn
            return fn

        return deco

    def notification(self, name: str):
        """Decorator: register an async handler for an inbound notification."""

        def deco(fn: NotificationHandler) -> NotificationHandler:
            self._notifications[name] = fn
            return fn

        return deco

    # ---- main loop ----

    async def serve(self) -> None:
        """Bind stdin, read JSON-RPC messages forever. Exit on EOF."""
        if self._reader is None:
            await self._bind_stdin()
        assert self._reader is not None
        self._running = True
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    # EOF — the IDE closed the pipe.
                    break
                await self._handle_line(line)
        finally:
            self._running = False
            await self._shutdown_tasks()

    async def _bind_stdin(self) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        try:
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except (NotImplementedError, OSError):
            # Windows / some test environments don't support pipe
            # connections via the proactor loop. Fall back to a
            # thread-based reader.
            await self._bind_stdin_via_thread()
            return
        self._reader = reader

    async def _bind_stdin_via_thread(self) -> None:
        """Fallback for environments where ``connect_read_pipe(stdin)``
        isn't supported. Spawns a thread that blocks on ``stdin.readline``
        and feeds the lines into an asyncio StreamReader."""
        reader = asyncio.StreamReader()
        loop = asyncio.get_running_loop()

        def _pump() -> None:
            for line in sys.stdin:
                loop.call_soon_threadsafe(
                    reader.feed_data,
                    line.encode("utf-8"),
                )
            loop.call_soon_threadsafe(reader.feed_eof)

        import threading

        threading.Thread(target=_pump, daemon=True, name="acp-stdin").start()
        self._reader = reader

    async def _handle_line(self, line: bytes) -> None:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("ignoring malformed JSON-RPC line: %r", text[:200])
            return
        if not isinstance(msg, dict):
            logger.warning("ignoring non-object JSON-RPC message")
            return
        # Route response, notification, or request.
        if "result" in msg or "error" in msg:
            self._route_response(msg)
            return
        method = msg.get("method")
        if not isinstance(method, str):
            logger.warning("ignoring message with no method")
            return
        # Reject requests that arrive during the shutdown window so
        # they don't get added to ``_tasks`` after the snapshot+clear
        # in ``_shutdown_tasks``. Mirrors the webhook server's
        # _stopping guard (commit 822d3a6).
        if self._stopping:
            msg_id = msg.get("id")
            if msg_id is not None:
                # Respond with a structured error so the IDE sees a
                # clean rejection instead of an indefinite hang.
                await self._send_error(
                    msg_id,
                    ERR_INTERNAL,
                    "server shutting down; request rejected",
                )
            return
        task = asyncio.create_task(self._dispatch(msg))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _route_response(self, msg: dict[str, Any]) -> None:
        """A response to one of our client-bound requests."""
        msg_id = msg.get("id")
        if msg_id is None or msg_id not in self._pending_client_responses:
            logger.warning(
                "received response with no matching pending id: %r",
                msg_id,
            )
            return
        future = self._pending_client_responses.pop(msg_id)
        if future.done():
            return
        if "error" in msg:
            future.set_exception(ACPError(msg["error"]))
        else:
            future.set_result(msg.get("result"))

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        method = msg["method"]
        params = msg.get("params") or {}
        if "id" in msg:
            await self._dispatch_request(msg["id"], method, params)
        else:
            await self._dispatch_notification(method, params)

    async def _dispatch_request(
        self,
        msg_id: Any,
        method: str,
        params: dict[str, Any],
    ) -> None:
        handler = self._methods.get(method)
        if handler is None:
            await self._send_error(
                msg_id,
                ERR_METHOD_NOT_FOUND,
                f"method not found: {method}",
            )
            return
        try:
            result = await handler(params)
        except ACPError as e:
            await self._send_error(msg_id, e.code, e.message, e.data)
        except Exception as e:
            logger.exception("method %s raised", method)
            await self._send_error(msg_id, ERR_INTERNAL, str(e))
            return
        await self._send_response(msg_id, result)

    async def _dispatch_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        handler = self._notifications.get(method)
        if handler is None:
            logger.debug("ignoring unknown notification: %s", method)
            return
        try:
            await handler(params)
        except Exception:
            logger.exception("notification %s handler raised", method)

    # ---- outbound ----

    async def send_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._write_message(msg)

    async def send_request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> Any:
        """Send a client-bound request and await the response.

        Each call allocates a fresh integer id; the matching response
        sets the registered future. Timeouts surface as
        :class:`asyncio.TimeoutError`.
        """
        self._client_request_id += 1
        msg_id = self._client_request_id
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending_client_responses[msg_id] = future
        msg = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }
        await self._write_message(msg)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_client_responses.pop(msg_id, None)
            raise

    async def _send_response(self, msg_id: Any, result: Any) -> None:
        msg = {"jsonrpc": "2.0", "id": msg_id, "result": result or {}}
        await self._write_message(msg)

    async def _send_error(
        self,
        msg_id: Any,
        code: int,
        message: str,
        data: Any = None,
    ) -> None:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        msg = {"jsonrpc": "2.0", "id": msg_id, "error": err}
        await self._write_message(msg)

    async def _write_message(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        async with self._stdout_lock:
            try:
                self._writer.write(line)
                # Flush so the IDE sees the bytes immediately —
                # otherwise the agent looks unresponsive while Python
                # buffers stdout.
                flush = getattr(self._writer, "flush", None)
                if flush is not None:
                    flush()
            except Exception:
                logger.exception("failed to write ACP message")

    # ---- shutdown ----

    async def _shutdown_tasks(self) -> None:
        """Drain in-flight dispatches and pending client-bound futures.

        Called on EOF so the process exits cleanly when the IDE closes
        the pipe. Two phases for dispatch tasks: grace, then cancel.
        Then resolve every pending client-request future so callers
        blocked in :meth:`send_request` unwind rather than hang.
        """
        # Latch BEFORE the snapshot so a request arriving in the next
        # few microseconds sees ``_stopping == True`` in ``_handle_line``
        # and 503s immediately without adding itself to the set we're
        # about to drain.
        self._stopping = True
        tasks = list(self._tasks)
        self._tasks.clear()
        if tasks:
            _done, pending = await asyncio.wait(
                tasks,
                timeout=5.0,
                return_when=asyncio.ALL_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        for future in list(self._pending_client_responses.values()):
            if not future.done():
                future.set_exception(
                    ACPError({"code": ERR_INTERNAL, "message": "server shutting down"})
                )
        self._pending_client_responses.clear()
        # Resolve any pending client-bound futures so callers waiting
        # on them unwind rather than hang.
        for future in list(self._pending_client_responses.values()):
            if not future.done():
                future.set_exception(
                    ACPError({"code": ERR_INTERNAL, "message": "server shutting down"})
                )
        self._pending_client_responses.clear()


class ACPError(Exception):
    """Raised by handlers to surface a JSON-RPC error to the client.

    Also raised when a client-bound request comes back with an
    ``error`` field — :attr:`error` carries the raw error object.
    """

    def __init__(self, error: dict[str, Any] | str) -> None:
        if isinstance(error, str):
            error = {"code": ERR_INTERNAL, "message": error}
        self.error = error
        self.code = int(error.get("code", ERR_INTERNAL))
        self.message = str(error.get("message", ""))
        self.data = error.get("data")
        super().__init__(self.message)
