"""Security-oriented @tool registrations (T-MIG).

Thin model-facing wrappers around athena/safety/tirith.py,
url_safety.py, and athena/safety/osv.py. Each tool returns
structured JSON the model can parse; failures (no backend,
no binary, no network) become structured verdicts, never
raise.

These are advisory tools — they return verdicts. The CALLING
code (Bash precheck hook, browser navigate, the model itself)
decides what to do with the verdict. Same shape as athena's
other advisory surfaces: diagnose, vision_analyze, etc.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import load_config
from .registry import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# tirith_check — pre-execution scanner for shell commands
# ---------------------------------------------------------------


@tool(
    name="tirith_check",
    toolset="safety",
    description=(
        "Inspect a shell command for content-level threats "
        "BEFORE running it (homograph URLs, pipe-to-interpreter, "
        "terminal injection via ANSI escapes, hidden Unicode "
        "bidi controls). Returns {action: allow|warn|block, "
        "findings: [...], summary: '...', available: bool}. "
        "Advisory — use the verdict to decide whether to run "
        "the command via Bash. Requires the external tirith "
        "binary (Linux / macOS); on Windows or when missing, "
        "returns available=false."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to inspect.",
            },
        },
        "required": ["command"],
    },
)
def tirith_check(command: str = "", **_kw: Any) -> str:
    if not command:
        return json.dumps({
            "action": "allow", "findings": [],
            "summary": "no command provided",
            "available": False,
        })
    from ..safety.tirith import check_command_security

    from ._active_cfg import active_cfg
    v = check_command_security(command, cfg=active_cfg())
    return json.dumps({
        "action": v.action,
        "findings": v.findings,
        "summary": v.summary,
        "available": v.available,
    })


# ---------------------------------------------------------------
# url_safety_check — explicit pre-fetch verdict for URLs
# ---------------------------------------------------------------


@tool(
    name="url_safety_check",
    toolset="safety",
    description=(
        "Check whether a URL is safe to fetch BEFORE issuing the "
        "request. Returns {safe: bool, reason: '...', resolved_ip: "
        "<str or null>}. Validates scheme (http/https only), "
        "resolves DNS, and rejects URLs that resolve to private / "
        "loopback / link-local / cloud-metadata / CGNAT / IPv6 ULA "
        "addresses (SSRF defense). Athena's WebFetch already "
        "validates internally; this exposes the verdict so the "
        "model can decide BEFORE invoking the fetch."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to validate.",
            },
        },
        "required": ["url"],
    },
)
def url_safety_check(url: str = "", **_kw: Any) -> str:
    if not url:
        return json.dumps({
            "safe": False,
            "reason": "no URL provided",
            "resolved_ip": None,
        })
    from ._active_cfg import active_cfg
    cfg = active_cfg()
    if not getattr(cfg, "url_safety_enabled", True):
        return json.dumps({
            "safe": True,
            "reason": "url_safety_enabled=False; check skipped",
            "resolved_ip": None,
        })
    from ..safety.url_safety import URLSecurityDenied, validate_url

    try:
        v = validate_url(url)
    except URLSecurityDenied as e:
        return json.dumps({
            "safe": False,
            "reason": str(e),
            "resolved_ip": None,
        })
    except Exception as e:  # noqa: BLE001
        # validate_url raises URLSecurityDenied + ValueError; catch
        # broadly so a future change doesn't crash this advisory.
        return json.dumps({
            "safe": False,
            "reason": f"validation error: {type(e).__name__}: {e}",
            "resolved_ip": None,
        })
    return json.dumps({
        "safe": True,
        "reason": "validated",
        "resolved_ip": v.resolved_ip,
    })


# ---------------------------------------------------------------
# osv_check — look up vulnerabilities for package@version
# ---------------------------------------------------------------


@tool(
    name="osv_check",
    toolset="safety",
    description=(
        "Query the Open Source Vulnerabilities database "
        "(osv.dev) for CVEs affecting a specific package "
        "version. Returns {available: bool, package, version, "
        "ecosystem, vulns: [{id, summary, severity, aliases, "
        "references}], error?}. Use BEFORE recommending a dep "
        "or running an install. Supported ecosystems include "
        "PyPI, npm, crates.io, Go, Maven, NuGet, RubyGems, "
        "Packagist, Hex, Pub, Debian, Ubuntu, Alpine, etc. "
        "Read-only HTTP — no credentials needed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": "Package name (e.g. 'requests', '@types/node', 'serde').",
            },
            "version": {
                "type": "string",
                "description": "Exact version string (e.g. '2.31.0').",
            },
            "ecosystem": {
                "type": "string",
                "description": (
                    "Package ecosystem: PyPI, npm, crates.io, Go, "
                    "Maven, NuGet, RubyGems, Packagist, Hex, Pub, "
                    "Debian, Ubuntu, Alpine, etc."
                ),
            },
        },
        "required": ["package", "version", "ecosystem"],
    },
)
def osv_check(
    package: str = "",
    version: str = "",
    ecosystem: str = "",
    **_kw: Any,
) -> str:
    from ._active_cfg import active_cfg
    cfg = active_cfg()
    if not getattr(cfg, "osv_enabled", True):
        return json.dumps({
            "available": False,
            "error": "osv_enabled=False; check skipped",
        })
    if not package or not version or not ecosystem:
        return json.dumps({
            "available": False,
            "error": "package + version + ecosystem all required",
        })

    from ..safety.osv import query

    vulns, error = query(
        package, version, ecosystem=ecosystem, cfg=cfg,
    )
    return json.dumps({
        "available": error is None,
        "package": package,
        "version": version,
        "ecosystem": ecosystem,
        "vulns": [v.to_dict() for v in vulns],
        "error": error,
    })
