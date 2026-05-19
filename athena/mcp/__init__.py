"""Model Context Protocol (MCP) integration for athena.

Currently supports the stdio transport. HTTP/SSE is intentionally deferred
since most useful MCP servers ship as stdio subprocesses and stdio works
in air-gapped contexts where HTTP often does not.
"""

from .client import MCPError, MCPStdioClient
from .loader import load_mcp_servers, shutdown_all

__all__ = ["MCPError", "MCPStdioClient", "load_mcp_servers", "shutdown_all"]
