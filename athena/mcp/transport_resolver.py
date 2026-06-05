"""Strategy dispatcher: pick the right MCP transport for an mcp.json entry.

Entries fall into two shapes:

- **stdio** (default): ``{"command": "...", "args": [...], ...}``.
  Constructs :class:`~athena.mcp.client.MCPStdioClient`. Backwards-
  compatible with every existing mcp.json — entries without an
  explicit ``transport`` field flow here.

- **sse / http**: ``{"transport": "sse", "url": "...", "oauth": {...}}``.
  Constructs :class:`~athena.mcp.sse_transport.SSETransport`.
  ``http`` is an alias for ``sse`` — the two transports look
  identical from athena's side; both POST JSON-RPC and receive
  responses over the SSE channel.

The resolver returns whichever transport class the entry asks for;
both implement the same synchronous public API
(``initialize / list_tools / call_tool / request / close``), so the
loader and tool registry don't need to branch on transport.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from .client import MCPStdioClient
    from .sse_transport import SSETransport

logger = logging.getLogger(__name__)


MCPTransport = Union["MCPStdioClient", "SSETransport"]
"""The transport types the resolver can return. They share a duck-typed
sync surface; we don't define a Protocol because the existing
:class:`MCPStdioClient` has more attributes (proc, stderr_buffer) than
the new SSE transport, and tightening the interface would break
back-compat with code that reaches for those."""


_SSE_LIKE = frozenset({"sse", "http", "http+sse"})


def open_transport(
    server_id: str,
    config: dict[str, Any],
    *,
    startup_timeout: float | None = None,
) -> MCPTransport:
    """Construct and return the transport for one mcp.json server entry.

    The returned transport is already opened (subprocess started for
    stdio; SSE connection up + endpoint event received for sse). The
    caller is responsible for ``.initialize()``, ``.list_tools()``, and
    eventually ``.close()``.

    ``startup_timeout`` (seconds), when given, bounds how long the
    handshake may take before the transport gives up — stdio maps it to
    the client's ``startup_timeout``, sse to the connection ``open_timeout``.
    None keeps each transport's own default. The loader passes an
    effective value (per-server override or global default) so a
    non-responsive server can't stall startup indefinitely.

    Raises:
      ValueError: for malformed config (unknown transport, missing
        required fields).
      Any transport-specific exception bubbles from the constructor.
    """
    transport = (config.get("transport") or "stdio").lower()
    if transport == "stdio":
        return _open_stdio(server_id, config, startup_timeout)
    if transport in _SSE_LIKE:
        return _open_sse(server_id, config, startup_timeout)
    raise ValueError(
        f"mcp server {server_id!r}: unknown transport {transport!r} (expected stdio, sse, or http)"
    )


def _open_stdio(
    server_id: str, config: dict[str, Any], startup_timeout: float | None = None
) -> MCPStdioClient:
    from .client import MCPStdioClient

    if "command" not in config:
        raise ValueError(f"mcp server {server_id!r}: stdio transport requires 'command'")
    kwargs: dict[str, Any] = {}
    if startup_timeout is not None:
        kwargs["startup_timeout"] = startup_timeout
    return MCPStdioClient(
        name=server_id,
        command=config["command"],
        args=config.get("args") or [],
        env=config.get("env"),
        cwd=config.get("cwd"),
        **kwargs,
    )


def _open_sse(
    server_id: str, config: dict[str, Any], startup_timeout: float | None = None
) -> SSETransport:
    from .oauth import OAuthConfig
    from .sse_transport import SSETransport

    url = config.get("url")
    if not url:
        raise ValueError(f"mcp server {server_id!r}: sse/http transport requires 'url'")

    oauth_cfg: OAuthConfig | None = None
    oauth_raw = config.get("oauth")
    if oauth_raw is not None:
        if not isinstance(oauth_raw, dict):
            raise ValueError(f"mcp server {server_id!r}: 'oauth' must be a table")
        oauth_cfg = _parse_oauth(server_id, oauth_raw)

    kwargs: dict[str, Any] = {}
    if startup_timeout is not None:
        kwargs["open_timeout"] = startup_timeout
    return SSETransport(
        server_id,
        base_url=url,
        oauth_cfg=oauth_cfg,
        **kwargs,
    )


def _parse_oauth(server_id: str, raw: dict[str, Any]) -> Any:
    """Map the mcp.json oauth subtree onto an :class:`OAuthConfig`."""
    from .oauth import OAuthConfig

    required = ("authorization_endpoint", "token_endpoint", "client_id")
    missing = [k for k in required if not raw.get(k)]
    if missing:
        raise ValueError(
            f"mcp server {server_id!r}: oauth missing required fields: {', '.join(missing)}"
        )
    scopes_raw = raw.get("scopes") or []
    if not isinstance(scopes_raw, list):
        raise ValueError(f"mcp server {server_id!r}: oauth.scopes must be a list")
    return OAuthConfig(
        server_id=server_id,
        authorization_endpoint=str(raw["authorization_endpoint"]),
        token_endpoint=str(raw["token_endpoint"]),
        client_id=str(raw["client_id"]),
        scopes=[str(s) for s in scopes_raw],
        audience=raw.get("audience"),
    )
