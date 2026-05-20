"""Per-request MCP JSONL log (T3-02 audit gap).

Each handled MCP request appends one line to ``~/.athena/mcp.jsonl``
with the summary fields a reviewer needs to triage a session:
request id, timestamp, client name, method, a params summary, a
result/error summary, latency. Full request/response bodies stay
off-log by default — the client knows what it sent, and bodies
inflate the file fast under any sustained tool-call load.

Module is named ``request_log`` rather than ``logging`` to avoid
shadowing the stdlib :mod:`logging` import inside the package
namespace (the existing :mod:`athena.proxy.logging` already burns
that hazard once; doing it again here is unnecessary).
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()


@dataclass
class McpRequestLog:
    """Append-only JSONL appender for MCP requests.

    ``log_path`` is absolute; the subcommand expands ``~/...`` before
    constructing the instance.
    """

    log_path: Path

    def record(
        self,
        *,
        request_id: str,
        client_name: str,
        method: str,
        params_summary: dict[str, Any] | None,
        result_summary: dict[str, Any] | None,
        latency_ms: float,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Append one summary line. Idempotent on disk; concurrent
        callers serialise on the module lock."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "request_id": request_id,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "client_name": client_name,
            "method": method,
            "params_summary": params_summary or {},
            "latency_ms": round(latency_ms, 2),
        }
        if result_summary is not None:
            entry["result_summary"] = result_summary
        if error is not None:
            entry["error"] = error

        line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
        try:
            with _WRITE_LOCK, open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            # Logging is best-effort — never let a disk error sink a
            # successful MCP response.
            logger.warning("mcp request log write failed: %s", e)


def summarise_params(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Compact summary of incoming params suitable for the log line.

    Avoids dumping full message bodies / tool argument blobs — just
    the fields a reviewer needs to grep / count by method."""
    if not isinstance(params, dict):
        return {}
    if method == "initialize":
        ci = params.get("clientInfo") or {}
        if isinstance(ci, dict):
            return {
                "client_name": ci.get("name", ""),
                "client_version": ci.get("version", ""),
            }
        return {}
    if method == "tools/call":
        args = params.get("arguments") or {}
        return {
            "tool_name": params.get("name", ""),
            "arg_count": len(args) if isinstance(args, dict) else 0,
        }
    if method == "resources/read":
        return {"uri": params.get("uri", "")}
    return {}


def summarise_result(method: str, result: Any) -> dict[str, Any]:
    """Compact summary of the result. ``tools/call`` and
    ``resources/read`` results carry the content; we record byte
    sizes + error flags only."""
    if not isinstance(result, dict):
        return {}
    if method == "tools/list":
        tools = result.get("tools") or []
        return {"tool_count": len(tools) if isinstance(tools, list) else 0}
    if method == "resources/list":
        resources = result.get("resources") or []
        return {"resource_count": len(resources) if isinstance(resources, list) else 0}
    if method == "tools/call":
        contents = result.get("content") or []
        body_bytes = sum(
            len(str((c or {}).get("text", ""))) for c in contents if isinstance(c, dict)
        )
        return {
            "content_blocks": len(contents),
            "body_bytes": body_bytes,
            "is_error": bool(result.get("isError")),
        }
    if method == "resources/read":
        contents = result.get("contents") or []
        body_bytes = sum(
            len(str((c or {}).get("text", ""))) for c in contents if isinstance(c, dict)
        )
        return {
            "content_blocks": len(contents),
            "body_bytes": body_bytes,
        }
    return {}
