"""Copy Hermes' mcp.json to athena v2's MCP registry.

The two formats are identical at the surface (a dict of named servers, each
with ``command`` / ``args`` / ``env`` / ``transport`` / ``url``). The only
athena v2 wrinkle: HTTP and SSE transports aren't supported until Phase 12,
so any such server is copied through with ``disabled=true`` and a WARNING
in the report.
"""

from __future__ import annotations

import json
from pathlib import Path

from .report import Report

_HTTP_LIKE = {"http", "https", "sse"}


def translate_mcp(
    source: Path,
    dest: Path,
    *,
    report: Report,
    dry_run: bool = False,
) -> None:
    mcp_src = source / "mcp.json"
    if not mcp_src.exists():
        report.add("mcp_warning", {"reason": "no_mcp_json", "path": str(mcp_src)})
        return

    try:
        data = json.loads(mcp_src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.add("mcp_error", {"path": str(mcp_src), "error": str(e)})
        return

    servers = data.get("mcpServers") or data.get("servers") or {}
    if not isinstance(servers, dict):
        report.add(
            "mcp_error",
            {
                "path": str(mcp_src),
                "error": "mcpServers/servers is not a mapping",
            },
        )
        return

    disabled_names: list[str] = []
    for name, conf in list(servers.items()):
        if not isinstance(conf, dict):
            continue
        transport = str(conf.get("transport") or "").lower()
        if transport in _HTTP_LIKE:
            conf["disabled"] = True
            disabled_names.append(name)
            report.add(
                "mcp_warning",
                {
                    "reason": "http_or_sse_transport_disabled_until_phase_12",
                    "server": name,
                    "transport": transport,
                },
            )

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "mcp.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    report.add(
        "imported_mcp",
        {
            "server_count": len(servers),
            "disabled_servers": disabled_names,
            "destination": str(dest / "mcp.json"),
            "dry_run": dry_run,
        },
    )
