"""Shared tool-status taxonomy.

The model is told — in the system prompt and tool descriptions — to
react to a tool's structured ``status`` field: e.g. surface a one-liner
on ``not_enabled``, treat ``not_configured`` as "enabled but no backend
resolved", retry elsewhere, etc. Those strings are a contract, so a
typo (``not_enabledd``) silently breaks the model's reaction with no
error anywhere.

``ToolStatus`` makes the set type-checked: a status that isn't a member
fails mypy at the construction site instead of misfiring in production.
Build payloads with :func:`status_payload` so the ``status`` value is
checked.

Used by the videogen tools today (the only capability-gated tool
surface). New capability-gated tools should reuse this rather than
hand-rolling status strings.
"""

from __future__ import annotations

import json
from typing import Any, Literal

ToolStatus = Literal[
    "done",  # success
    "declined",  # user declined a confirmation prompt
    "error",  # backend/runtime error (detail in an "error" field)
    "timeout",  # backend timed out
    "cancelled",  # cancelled mid-flight
    "rejected",  # bad input — rejected before doing work
    "not_enabled",  # capability gated off in config
    "not_configured",  # enabled but no backend/credentials resolved
]


def status_payload(status: ToolStatus, **fields: Any) -> str:
    """Return a JSON tool-result payload with a type-checked ``status``.

    ``status_payload("not_enabledd", ...)`` is a mypy error — the typo
    isn't a :data:`ToolStatus` member.
    """
    return json.dumps({"status": status, **fields})
