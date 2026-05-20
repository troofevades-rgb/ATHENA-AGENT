"""MCP server core for athena (T3-02.4).

Stateless JSON-RPC dispatch — one ``AthenaMCPServer`` per
connection, owning the curated tools + resources surfaces. The
transport (stdio / SSE) drives ``handle_request`` for each incoming
message; ``handle_request`` returns ``None`` for notifications and
a response dict otherwise.

Capability advertisement is honest: we expose ``tools`` and
``resources``. We do NOT advertise ``prompts`` (no prompt
templates) or ``sampling`` (we're a server, not a sampler) — fake
capabilities cause MCP clients to call methods we don't implement.

JSON-RPC error codes follow the spec:
  -32600 invalid request
  -32601 method not found
  -32602 invalid params
  -32603 internal error
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .request_log import McpRequestLog, summarise_params, summarise_result
from .resources import RESOURCE_DESCRIPTORS, AthenaMCPResources
from .tools import TOOL_DESCRIPTORS, AthenaMCPTools

logger = logging.getLogger(__name__)


PROTOCOL_VERSION = "2024-11-05"

# JSON-RPC error codes from the spec.
_ERR_METHOD_NOT_FOUND = -32601
_ERR_INVALID_PARAMS = -32602
_ERR_INTERNAL = -32603


@dataclass
class AthenaMCPServer:
    """Stateless MCP server. One per connection.

    ``tools`` and ``resources`` are the curated surfaces built by
    the subcommand wiring; tests inject a stub of each.

    ``differentiated`` is the T5-05.3 differentiated-capability
    surface (verified_write, rollback_to, analyze_image, recall,
    ...). Optional — when None, only the base ``tools`` set is
    advertised; the curated read-only T3-02 surface stays as the
    fallback.
    """

    tools: AthenaMCPTools
    resources: AthenaMCPResources
    request_log: McpRequestLog | None = None
    differentiated: Any = None  # DifferentiatedTools | None
    _initialized: bool = False
    _client_name: str = ""

    def handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC request.

        Returns the response dict to send back, or ``None`` if the
        message was a notification (per JSON-RPC, no ``id`` ⇒ no
        response).
        """
        import time as _time

        method = str(req.get("method") or "")
        params = req.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        req_id = req.get("id")
        is_notification = req_id is None
        start = _time.time()
        result: Any = None
        error_payload: dict[str, Any] | None = None

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "notifications/initialized":
                self._initialized = True
                return None
            elif method == "tools/list":
                tools_list = list(TOOL_DESCRIPTORS)
                if self.differentiated is not None:
                    tools_list.extend(self.differentiated.descriptors)
                result = {"tools": tools_list}
            elif method == "tools/call":
                tool_name = str(params.get("name") or "")
                tool_args = params.get("arguments") or {}
                if not isinstance(tool_args, dict):
                    return self._error(req_id, _ERR_INVALID_PARAMS, "arguments must be an object")
                # Try the differentiated surface first (its names
                # don't collide with the base curated tools — those
                # are athena_-prefixed). Falls back to the base
                # surface when the name doesn't match.
                if self.differentiated is not None and any(
                    d["name"] == tool_name for d in self.differentiated.descriptors
                ):
                    result = self.differentiated.call(tool_name, tool_args)
                else:
                    result = self.tools.call_tool(tool_name, tool_args)
            elif method == "resources/list":
                result = {"resources": RESOURCE_DESCRIPTORS}
            elif method == "resources/read":
                uri = str(params.get("uri") or "")
                result = self.resources.read_resource(uri)
            elif method == "ping":
                result = {}
            else:
                if is_notification:
                    # Unrecognised notification — silently drop (spec
                    # says servers may ignore unknown notifications).
                    return None
                err_resp = self._error(
                    req_id,
                    _ERR_METHOD_NOT_FOUND,
                    f"method not found: {method}",
                )
                error_payload = err_resp["error"]
                self._record_request(req_id, method, params, None, error_payload, start)
                return err_resp
        except Exception as e:  # noqa: BLE001
            logger.exception("MCP handler error for method=%s", method)
            if is_notification:
                return None
            err_resp = self._error(req_id, _ERR_INTERNAL, f"internal error: {e}")
            error_payload = err_resp["error"]
            self._record_request(req_id, method, params, None, error_payload, start)
            return err_resp

        if is_notification:
            return None
        # Track the client name from initialize for subsequent log
        # lines. ``initialize`` is the first call, so this lands
        # before any tool/resource call's record() fires.
        if method == "initialize":
            ci = params.get("clientInfo") or {}
            if isinstance(ci, dict):
                self._client_name = str(ci.get("name") or "")
        self._record_request(req_id, method, params, result, None, start)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _record_request(
        self,
        req_id: Any,
        method: str,
        params: dict[str, Any],
        result: Any,
        error: dict[str, Any] | None,
        start: float,
    ) -> None:
        if self.request_log is None:
            return
        import time as _time

        latency_ms = (_time.time() - start) * 1000.0
        try:
            self.request_log.record(
                request_id=str(req_id) if req_id is not None else "",
                client_name=self._client_name,
                method=method,
                params_summary=summarise_params(method, params),
                result_summary=summarise_result(method, result) if result is not None else None,
                latency_ms=latency_ms,
                error=error,
            )
        except Exception:  # noqa: BLE001
            # Logging is best-effort; never let it sink a successful
            # MCP response.
            logger.debug("MCP request_log.record failed", exc_info=True)

    # ---- handlers ----------------------------------------------------

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        client_info = params.get("clientInfo") or {}
        if isinstance(client_info, dict):
            logger.info(
                "MCP client connected: name=%s version=%s",
                client_info.get("name"),
                client_info.get("version"),
            )
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": _server_info(),
        }

    def _error(self, req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


def _server_info() -> dict[str, Any]:
    try:
        from .. import __version__ as athena_version
    except ImportError:  # pragma: no cover
        athena_version = "?"
    return {"name": "athena-mcp-server", "version": str(athena_version)}
