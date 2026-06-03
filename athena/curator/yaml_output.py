"""Parse the curator's structured YAML output.

The curator prompt instructs the fork to emit its decisions inside a fenced
``yaml-curator-report`` block. The parser:

1. Extracts the fenced block (or accepts a bare YAML body).
2. ``yaml.safe_load`` it.
3. Validates the schema:
   - ``runs`` key → list of records
   - each record has ``skill``, ``decision``, ``rationale``
   - ``decision`` is one of the allowed set (KEEP_AS_IS, CONSOLIDATE_INTO,
     CREATE_UMBRELLA, DEMOTE_TO_REFERENCES, DEMOTE_TO_TEMPLATES,
     DEMOTE_TO_SCRIPTS, PRUNE)
   - decisions that require a target carry a non-empty ``target``
   - ``absorbed_into`` is captured as-is (null OK; the umbrella name
     drives downstream reference migration)

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

# Wide enum (Retrofit #10). The narrower legacy set
# {KEEP_AS_IS, CONSOLIDATE_INTO, CREATE_UMBRELLA, PRUNE} remains a
# subset — old-shape reports parse cleanly.
_ALLOWED_DECISIONS = frozenset(
    {
        "KEEP_AS_IS",
        "CONSOLIDATE_INTO",
        "CREATE_UMBRELLA",
        "DEMOTE_TO_REFERENCES",
        "DEMOTE_TO_TEMPLATES",
        "DEMOTE_TO_SCRIPTS",
        "PRUNE",
    }
)

# Decisions that REQUIRE a non-empty target. CREATE_UMBRELLA's target is
# the new umbrella's name; CONSOLIDATE_INTO's and the DEMOTE_TO_*'s are
# the existing umbrella absorbing this skill's content.
_TARGET_REQUIRED = frozenset(
    {
        "CONSOLIDATE_INTO",
        "CREATE_UMBRELLA",
        "DEMOTE_TO_REFERENCES",
        "DEMOTE_TO_TEMPLATES",
        "DEMOTE_TO_SCRIPTS",
    }
)

# Decisions that produce an ``absorbed_into`` umbrella for the
# reference-migration cron. CREATE_UMBRELLA is excluded — that row IS
# the umbrella, it is not being absorbed.
_ABSORPTION_DECISIONS = frozenset(
    {
        "CONSOLIDATE_INTO",
        "DEMOTE_TO_REFERENCES",
        "DEMOTE_TO_TEMPLATES",
        "DEMOTE_TO_SCRIPTS",
    }
)

_REQUIRED_KEYS = ("skill", "decision", "rationale")


def parse_curator_report(text: str) -> dict[str, Any] | None:
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
                i,
                decision,
            )
            return None

        # absorbed_into: optional from the model but the parser fills in
        # a default for absorption decisions when it's missing — the
        # umbrella that absorbed this skill is, by definition, the
        # target (CONSOLIDATE_INTO) or umbrella-name (DEMOTE_TO_*).
        # CREATE_UMBRELLA / KEEP_AS_IS / PRUNE always end up with None.
        absorbed_raw = entry.get("absorbed_into")
        if isinstance(absorbed_raw, str) and absorbed_raw:
            absorbed_into: str | None = absorbed_raw
        elif decision in _ABSORPTION_DECISIONS and isinstance(target, str):
            absorbed_into = target
        else:
            absorbed_into = None

        cleaned.append(
            {
                "skill": str(entry["skill"]),
                "decision": decision,
                "target": target if isinstance(target, str) and target else None,
                "absorbed_into": absorbed_into,
                "rationale": str(entry["rationale"]),
            }
        )

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
