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

    v = check_command_security(command, cfg=load_config())
    return json.dumps({
        "action": v.action,
        "findings": v.findings,
        "summary": v.summary,
        "available": v.available,
    })
