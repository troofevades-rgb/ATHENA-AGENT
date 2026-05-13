"""Parse the curator's structured YAML output.

The curator prompt instructs the fork to emit its decisions inside a fenced
``yaml-curator-report`` block. The parser:

1. Extracts the fenced block (or accepts a bare YAML body).
2. ``yaml.safe_load`` it.
3. Validates the schema (``runs`` key → list of records with required
   fields and a decision in the allowed set).

Returns ``None`` on any failure so callers can reject the run without
mutating state. We never raise to the caller — the curator is a background
process and failures should produce a log warning, not a stack trace.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import yaml


logger = logging.getLogger(__name__)


_FENCE_RE = re.compile(
    r"```yaml-curator-report\s*\n(.*?)\n```",
    re.S,
)

_ALLOWED_DECISIONS = frozenset({
    "KEEP_AS_IS", "CONSOLIDATE_INTO", "CREATE_UMBRELLA", "PRUNE",
})
_TARGET_REQUIRED = frozenset({"CONSOLIDATE_INTO", "CREATE_UMBRELLA"})
_REQUIRED_KEYS = ("skill", "decision", "rationale")


def parse_curator_report(text: str) -> dict | None:
    """Return the parsed report dict, or None when the input is malformed."""
    if not text:
        logger.warning("curator output is empty")
        return None

    block = _extract_block(text)
    if block is None:
        logger.warning("curator output missing yaml-curator-report fence")
        return None

    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as e:
        logger.warning("curator yaml parse failed: %s", e)
        return None

    if not isinstance(data, dict) or "runs" not in data:
        logger.warning("curator output missing 'runs' key")
        return None

    runs = data["runs"]
    if not isinstance(runs, list):
        logger.warning("curator 'runs' is not a list")
        return None

    cleaned: list[dict[str, Any]] = []
    for i, entry in enumerate(runs):
        if not isinstance(entry, dict):
            logger.warning("curator run %d is not a mapping", i)
            return None
        for key in _REQUIRED_KEYS:
            if key not in entry:
                logger.warning("curator run %d missing required key %r", i, key)
                return None
        decision = entry["decision"]
        if decision not in _ALLOWED_DECISIONS:
            logger.warning("curator run %d has unknown decision %r", i, decision)
            return None
        target = entry.get("target")
        if decision in _TARGET_REQUIRED and not (isinstance(target, str) and target):
            logger.warning(
                "curator run %d has decision %s but missing/empty target",
                i, decision,
            )
            return None
        cleaned.append({
            "skill": str(entry["skill"]),
            "decision": decision,
            "target": target if isinstance(target, str) and target else None,
            "rationale": str(entry["rationale"]),
        })

    return {"runs": cleaned}


def _extract_block(text: str) -> str | None:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # Allow a bare body when the fence wasn't used — be permissive on input
    # but firm on schema.
    if "runs:" in text:
        return text.strip()
    return None
