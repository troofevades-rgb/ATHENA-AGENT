"""Audit log query + diff (T3-04).

This package is read-only — it reads the JSONL files that
``athena.safety.audit.MutationAuditLog`` and
``athena.agent.checkpoints.CheckpointAuditLog`` already write, and
turns time-ranged queries into human-readable or JSON diffs.

The two public surfaces are :mod:`athena.audit.timestamps` (parses
ISO 8601 / relative / special-token timestamps) and
:mod:`athena.audit.diff` (replay + render).
"""

from .diff import (
    MEMORY_TOOL_NAMES,
    SKILL_TOOL_NAMES,
    MemoryEvent,
    RollbackMarker,
    SkillEvent,
    collect_memory_events,
    collect_rollback_markers,
    collect_skill_events,
    render_memory_diff,
    render_memory_diff_json,
    render_skill_diff,
    render_skill_diff_json,
)
from .timestamps import TimestampParseError, parse_timestamp

__all__ = [
    "MEMORY_TOOL_NAMES",
    "SKILL_TOOL_NAMES",
    "MemoryEvent",
    "RollbackMarker",
    "SkillEvent",
    "TimestampParseError",
    "collect_memory_events",
    "collect_rollback_markers",
    "collect_skill_events",
    "parse_timestamp",
    "render_memory_diff",
    "render_memory_diff_json",
    "render_skill_diff",
    "render_skill_diff_json",
]
