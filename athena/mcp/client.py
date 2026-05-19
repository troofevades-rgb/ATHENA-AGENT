"""MCP stdio JSON-RPC client.

Wire format:
    Each direction is newline-delimited JSON. One JSON-RPC 2.0 message per line,
    no embedded newlines. Server's stderr is captured separately for diagnostics
    and surfaced via /mcp logs.

Concurrency model:
    The constructor spawns the server subprocess and two daemon threads:
      - reader thread: pulls lines from stdout, dispatches responses to pending
        Futures (by id), forwards server-originated notifications to a handler.
      - stderr thread: collects stderr lines into a ring buffer for diagnostics.
    The public API (initialize / list_tools / call_tool / request) is synchronous.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutTimeout
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class MCPStdioClient:
    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        startup_timeout: float = 30.0,
        request_timeout: float = 60.0,
    ):
        self.name = name
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout

        env_full = {**os.environ, **(env or {})}
        # Don't let the server inherit a TTY-fd or buffer assumptions
        env_full.setdefault("PYTHONUNBUFFERED", "1")

        try:
            self.proc = subprocess.Popen(
                [command, *(args or [])],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line-buffered on the Python side
                encoding="utf-8",
                errors="replace",
                env=env_full,
                cwd=cwd,
            )
        except FileNotFoundError as e:
            raise MCPError(f"command not found: {command}") from e
        except OSError as e:
            raise MCPError(f"failed to spawn {command}: {e}") from e

        self._next_id = 1
        self._id_lock = threading.Lock()
        self._pending: dict[int, Future] = {}
        self._pending_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()

        self._stderr_lines: list[str] = []
        self._stderr_lock = threading.Lock()

        self._tools: list[dict[str, Any]] | None = None
        self._server_info: dict[str, Any] = {}
        self._initialized = False

        self._reader = threading.Thread(target=self._read_loop, name=f"mcp-{name}-rd", daemon=True)
        self._stderr_reader = threading.Thread(
            target=self._stderr_loop, name=f"mcp-{name}-err", daemon=True
        )
        self._reader.start()
        self._stderr_reader.start()

    # ---- public API -----------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        """Run MCP handshake. Returns server info from initialize response."""
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "roots": {"listChanged": False},
                    # We don't implement sampling; servers will see this absent.
                },
                "clientInfo": {"name": "athena", "version": "0.1.0"},
            },
            timeout=self.startup_timeout,
        )
        # Per spec: client must send 'notifications/initialized' before any other request.
        self.notify("notifications/initialized")
        self._server_info = result
        self._initialized = True
        return result

    def list_tools(self, refresh: bool = False) -> list[dict[str, Any]]:
        if self._tools is not None and not refresh:
            return self._tools
        result = self.request("tools/list")
        self._tools = result.get("tools", []) or []
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("tools/call", {"name": tool_name, "arguments": arguments or {}})

    def stderr_tail(self, n: int = 50) -> list[str]:
        with self._stderr_lock:
            return list(self._stderr_lines[-n:])

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        self._stop.set()
        # Try a graceful shutdown: close stdin, give the process a moment
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        # Fail any still-pending futures
        with self._pending_lock:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(MCPError(f"server '{self.name}' closed"))
            self._pending.clear()

    # ---- low-level send/recv -------------------------------------------

    def request(
        self, method: str, params: dict | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        with self._id_lock:
            req_id = self._next_id
            self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        fut: Future = Future()
        with self._pending_lock:
            self._pending[req_id] = fut
        self._send(msg)
        try:
            response = fut.result(timeout=timeout or self.request_timeout)
        except FutTimeout:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise MCPError(f"timeout waiting for {method!r} from '{self.name}'")
        if "error" in response:
            err = response["error"] or {}
            raise MCPError(f"{self.name}.{method}: {err.get('code')} {err.get('message')}")
        return response.get("result", {}) or {}

    def notify(self, method: str, params: dict | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def _send(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        with self._send_lock:
            try:
                self.proc.stdin.write(line)  # type: ignore[union-attr]
                self.proc.stdin.flush()  # type: ignore[union-attr]
            except (BrokenPipeError, OSError, AttributeError) as e:
                raise MCPError(f"server '{self.name}' pipe broken: {e}")

    # ---- background loops ----------------------------------------------

    def _read_loop(self) -> None:
        try:
            for line in self.proc.stdout:  # type: ignore[arg-type]
                if self._stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    # Some servers occasionally print to stdout; treat as log.
                    with self._stderr_lock:
                        self._stderr_lines.append(f"[stdout-junk] {line}")
                        self._stderr_lines = self._stderr_lines[-500:]
                    continue
                self._dispatch(msg)
        finally:
            # Server's stdout closed -> server exited or reader stopped.
            with self._pending_lock:
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(MCPError(f"server '{self.name}' exited"))
                self._pending.clear()

    def _stderr_loop(self) -> None:
        try:
            for line in self.proc.stderr:  # type: ignore[arg-type]
                if self._stop.is_set():
                    break
                line = line.rstrip()
                with self._stderr_lock:
                    self._stderr_lines.append(line)
                    if len(self._stderr_lines) > 500:
                        self._stderr_lines = self._stderr_lines[-500:]
        except Exception:
            pass

    def _dispatch(self, msg: dict[str, Any]) -> None:
        # Response to one of our requests
        if "id" in msg and ("result" in msg or "error" in msg):
            with self._pending_lock:
                fut = self._pending.pop(msg["id"], None)
            if fut and not fut.done():
                fut.set_result(msg)
            return
        # Server-initiated request: politely refuse anything we don't implement.
        if "method" in msg and "id" in msg:
            try:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "error": {"code": -32601, "message": "method not implemented by athena"},
                    }
                )
            except MCPError:
                # Pipe is broken — let the read loop's own EOF handling unwind.
                pass
            return
        # Notification from server (e.g. notifications/message) — ignore quietly.
        # We could log these to stderr_lines if desired.


def format_tool_result(result: dict[str, Any]) -> str:
    """Flatten an MCP tools/call result into a string for the model."""
    is_error = bool(result.get("isError"))
    parts: list[str] = []
    for block in result.get("content", []) or []:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "image":
            parts.append(
                f"[image: {block.get('mimeType', '?')}, "
                f"{len(block.get('data', '')) // 1024}KB base64 omitted]"
            )
        elif btype == "resource":
            res = block.get("resource", {}) or {}
            parts.append(f"[resource: {res.get('uri', '?')}]")
            if "text" in res:
                parts.append(res["text"])
        else:
            parts.append(f"[unknown content block: {btype}]")
    body = "\n".join(p for p in parts if p)
    return f"ERROR: {body}" if is_error else (body or "(empty)")
