"""Model Context Protocol (MCP) integration for athena.

Two roles:

- **Client** (existing) — athena consumes MCP servers configured in
  ``mcp.json``. Stdio + HTTP/SSE transports; OAuth handled in
  :mod:`athena.mcp.oauth`. See :class:`MCPStdioClient`.
- **Server** (T3-02) — ``athena mcp serve`` exposes a curated
  read-only + snapshot-revert tool surface to peer MCP clients
  (Claude Desktop, Claude Code, Cursor, etc.). See
  :mod:`athena.mcp.server`, :mod:`athena.mcp.tools`,
  :mod:`athena.mcp.resources`, :mod:`athena.mcp.transport_stdio`.

MCP spec version: 2024-11-05. We hand-roll the JSON-RPC framing
matching :mod:`athena.mcp.demo_server` (proven sync stdlib pattern)
rather than pulling the ``mcp`` SDK — no new dependency, and the
demo server is already a ~120-line reference of exactly what we
need.
"""

from .client import MCPError, MCPStdioClient
from .loader import load_mcp_servers, shutdown_all

__all__ = ["MCPError", "MCPStdioClient", "load_mcp_servers", "shutdown_all"]
