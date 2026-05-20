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
    """

    tools: AthenaMCPTools
    resources: AthenaMCPResources
    _initialized: bool = False

    def handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC request.

        Returns the response dict to send back, or ``None`` if the
        message was a notification (per JSON-RPC, no ``id`` ⇒ no
        response).
        """
        method = str(req.get("method") or "")
        params = req.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        req_id = req.get("id")
        is_notification = req_id is None

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "notifications/initialized":
                self._initialized = True
                return None
            elif method == "tools/list":
                result = {"tools": TOOL_DESCRIPTORS}
            elif method == "tools/call":
                tool_name = str(params.get("name") or "")
                tool_args = params.get("arguments") or {}
                if not isinstance(tool_args, dict):
                    return self._error(req_id, _ERR_INVALID_PARAMS, "arguments must be an object")
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
                return self._error(
                    req_id,
                    _ERR_METHOD_NOT_FOUND,
                    f"method not found: {method}",
                )
        except Exception as e:  # noqa: BLE001
            logger.exception("MCP handler error for method=%s", method)
            if is_notification:
                return None
            return self._error(req_id, _ERR_INTERNAL, f"internal error: {e}")

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

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
