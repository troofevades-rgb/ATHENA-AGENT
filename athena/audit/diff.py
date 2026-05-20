"""Audit-log replay between two timestamps (T3-04).

Adapter over athena's existing audit surfaces:

- ``athena.safety.audit.MutationAuditLog`` writes file-mutation
  records to ``<audit_dir>/mutations-YYYY-MM.jsonl`` (one row per
  tracked write). Each record carries ``timestamp``, ``tool_name``,
  ``path``, ``write_origin``, ``sha_before``, ``sha_after``,
  ``byte_delta``, ``snapshot_id``.

- ``athena.agent.checkpoints.CheckpointAuditLog`` writes
  ``checkpoint`` and ``rollback`` events to
  ``<checkpoint_dir>/audit.jsonl`` per session.

This module walks both, classifies entries by tool_name prefix
(``skill_*`` → skill event, ``memory_*`` → memory event), filters
the time window, and renders human-readable or JSON output.

Content diff: ``MutationAuditLog`` records SHA digests but not the
file content itself (the content is recoverable from the linked
``snapshot_id`` if needed). The diff prints ``sha_before`` /
``sha_after`` and ``byte_delta``; full text-diff is reserved for a
follow-up that extracts the snapshot tarball on demand.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from pathlib import Path
from typing import Any

# Actual tool_names that land in MutationAuditLog from
# athena/skills/manager.py + athena/memory/providers/builtin_file.py
# Plus skill_rollback from athena/cli/skill.py.
SKILL_TOOL_NAMES = frozenset(
    {
        "skill_create",
        "skill_patch",
        "skill_delete",
        "skill_write_file",
        "skill_rollback",
        "skill_manage",  # historical name; tolerated
    }
)
MEMORY_TOOL_NAMES = frozenset(
    {
        "memory_write",
        "memory_delete",
        "memory_update",  # spec name; tolerated
    }
)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SkillEvent:
    timestamp: str
    tool_name: str
    skill_name: str
    write_origin: str
    sha_before: str | None
    sha_after: str | None
    byte_delta: int
    path: str
    snapshot_id: str | None

    @property
    def category(self) -> str:
        """Bucket the tool_name into added / modified / removed."""
        if self.tool_name == "skill_create":
            return "added"
        if self.tool_name == "skill_delete":
            return "removed"
        return "modified"


@dataclasses.dataclass
class MemoryEvent:
    timestamp: str
    tool_name: str
    memory_name: str
    write_origin: str
    sha_before: str | None
    sha_after: str | None
    byte_delta: int
    path: str
    snapshot_id: str | None

    @property
    def category(self) -> str:
        if self.tool_name == "memory_delete":
            return "removed"
        if self.sha_before is None:
            return "added"
        return "modified"


@dataclasses.dataclass
class RollbackMarker:
    timestamp: str
    event_type: str  # "checkpoint" | "rollback"
    summary: str
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_skill_events(
    *,
    audit_dir: Path,
    since: _dt.datetime,
    until: _dt.datetime,
    actor: str | None = None,
) -> list[SkillEvent]:
    """Walk ``<audit_dir>/mutations-*.jsonl`` and return skill events
    in the window, oldest-first."""
    out: list[SkillEvent] = []
    for entry in _iter_mutation_records(audit_dir, since=since, until=until):
        tool = str(entry.get("tool_name") or "")
        if tool not in SKILL_TOOL_NAMES:
            continue
        if actor and entry.get("write_origin") != actor:
            continue
        path = str(entry.get("path") or "")
        out.append(
            SkillEvent(
                timestamp=str(entry.get("timestamp") or ""),
                tool_name=tool,
                skill_name=_extract_skill_name(path),
                write_origin=str(entry.get("write_origin") or "?"),
                sha_before=_or_none(entry.get("sha_before")),
                sha_after=_or_none(entry.get("sha_after")),
                byte_delta=int(entry.get("byte_delta") or 0),
                path=path,
                snapshot_id=_or_none(entry.get("snapshot_id")),
            )
        )
    out.sort(key=lambda e: e.timestamp)
    return out


def collect_memory_events(
    *,
    audit_dir: Path,
    since: _dt.datetime,
    until: _dt.datetime,
    actor: str | None = None,
) -> list[MemoryEvent]:
    out: list[MemoryEvent] = []
    for entry in _iter_mutation_records(audit_dir, since=since, until=until):
        tool = str(entry.get("tool_name") or "")
        if tool not in MEMORY_TOOL_NAMES:
            continue
        if actor and entry.get("write_origin") != actor:
            continue
        path = str(entry.get("path") or "")
        out.append(
            MemoryEvent(
                timestamp=str(entry.get("timestamp") or ""),
                tool_name=tool,
                memory_name=_extract_memory_name(path),
                write_origin=str(entry.get("write_origin") or "?"),
                sha_before=_or_none(entry.get("sha_before")),
                sha_after=_or_none(entry.get("sha_after")),
                byte_delta=int(entry.get("byte_delta") or 0),
                path=path,
                snapshot_id=_or_none(entry.get("snapshot_id")),
            )
        )
    out.sort(key=lambda e: e.timestamp)
    return out


def collect_rollback_markers(
    *,
    profile_dir: Path,
    since: _dt.datetime,
    until: _dt.datetime,
) -> list[RollbackMarker]:
    """Walk every per-session checkpoint audit log under the active
    profile and return any rollback / checkpoint event in the
    window, oldest-first."""
    out: list[RollbackMarker] = []
    ckpt_root = profile_dir / "checkpoints"
    if not ckpt_root.exists():
        return out
    for audit_path in ckpt_root.rglob("audit.jsonl"):
        try:
            text = audit_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = str(rec.get("ts") or "")
            if not _in_window(ts_str, since, until):
                continue
            event_type = str(rec.get("event_type") or "")
            if event_type not in ("checkpoint", "rollback"):
                continue
            out.append(
                RollbackMarker(
                    timestamp=ts_str,
                    event_type=event_type,
                    summary=str(rec.get("summary") or ""),
                    data=rec.get("data") or {},
                )
            )
    out.sort(key=lambda m: m.timestamp)
    return out


# ---------------------------------------------------------------------------
# Rendering — human-readable
# ---------------------------------------------------------------------------


_ICONS = {
    "added": "+",
    "modified": "~",
    "removed": "-",
}


def render_skill_diff(
    events: list[SkillEvent],
    *,
    since: _dt.datetime,
    until: _dt.datetime,
    rollbacks: list[RollbackMarker] | None = None,
) -> str:
    return _render(
        kind="Skill",
        events=[_render_skill_event(e) for e in events],
        summary=_summarise_skill(events),
        since=since,
        until=until,
        rollbacks=rollbacks,
    )


def render_memory_diff(
    events: list[MemoryEvent],
    *,
    since: _dt.datetime,
    until: _dt.datetime,
    rollbacks: list[RollbackMarker] | None = None,
) -> str:
    return _render(
        kind="Memory",
        events=[_render_memory_event(e) for e in events],
        summary=_summarise_memory(events),
        since=since,
        until=until,
        rollbacks=rollbacks,
    )


def _render_skill_event(e: SkillEvent) -> list[str]:
    verb = {
        "added": "Created",
        "modified": "Modified",
        "removed": "Deleted",
    }[e.category]
    icon = _ICONS[e.category]
    out = [f"{icon} {verb}: {e.skill_name}"]
    out.append(f"     at {e.timestamp} by {e.write_origin} (tool: {e.tool_name})")
    if e.sha_before or e.sha_after:
        out.append(
            "     sha: "
            + f"{(e.sha_before or '∅')[:12]} -> {(e.sha_after or '∅')[:12]}"
            + (f"  ({e.byte_delta:+d} bytes)" if e.byte_delta else "")
        )
    if e.snapshot_id:
        out.append(f"     snapshot: {e.snapshot_id}")
    out.append("     diff: [content not in audit log — recover from snapshot]")
    return out


def _render_memory_event(e: MemoryEvent) -> list[str]:
    verb = {
        "added": "Added",
        "modified": "Updated",
        "removed": "Deleted",
    }[e.category]
    icon = _ICONS[e.category]
    out = [f"{icon} {verb}: {e.memory_name}"]
    out.append(f"     at {e.timestamp} by {e.write_origin} (tool: {e.tool_name})")
    if e.sha_before or e.sha_after:
        out.append(
            "     sha: "
            + f"{(e.sha_before or '∅')[:12]} -> {(e.sha_after or '∅')[:12]}"
            + (f"  ({e.byte_delta:+d} bytes)" if e.byte_delta else "")
        )
    if e.snapshot_id:
        out.append(f"     snapshot: {e.snapshot_id}")
    out.append("     diff: [content not in audit log — recover from snapshot]")
    return out


def _summarise_skill(events: list[SkillEvent]) -> dict[str, int]:
    out = {"added": 0, "modified": 0, "removed": 0}
    for e in events:
        out[e.category] += 1
    return out


def _summarise_memory(events: list[MemoryEvent]) -> dict[str, int]:
    out = {"added": 0, "modified": 0, "removed": 0}
    for e in events:
        out[e.category] += 1
    return out


def _render(
    *,
    kind: str,
    events: list[list[str]],
    summary: dict[str, int],
    since: _dt.datetime,
    until: _dt.datetime,
    rollbacks: list[RollbackMarker] | None,
) -> str:
    since_str = since.isoformat() + "Z"
    until_str = until.isoformat() + "Z"
    if not events:
        return f"{kind} changes between {since_str} and {until_str}:\n  (no changes)\n"
    lines: list[str] = [
        f"{kind} changes between {since_str} and {until_str}:",
        "",
    ]
    for ev_lines in events:
        lines.extend(ev_lines)
        lines.append("")

    if rollbacks:
        lines.append(
            "Rollback / checkpoint events in this window (some changes "
            "above may have been reverted):"
        )
        for rb in rollbacks:
            lines.append(f"    {rb.timestamp}  {rb.event_type}  {rb.summary}")
        lines.append("")

    duration = until - since
    lines.append(
        f"Summary: {summary['added']} added, {summary['modified']} modified, "
        f"{summary['removed']} removed over {_format_duration(duration)}"
    )
    return "\n".join(lines) + "\n"


def _format_duration(d: _dt.timedelta) -> str:
    total = int(d.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} days")
    if hours:
        parts.append(f"{hours} hours")
    if mins and not days:
        parts.append(f"{mins} minutes")
    return ", ".join(parts) or "0 minutes"


# ---------------------------------------------------------------------------
# Rendering — JSON
# ---------------------------------------------------------------------------


def render_skill_diff_json(
    events: list[SkillEvent],
    *,
    since: _dt.datetime,
    until: _dt.datetime,
    rollbacks: list[RollbackMarker] | None = None,
) -> str:
    return _render_json(
        events=[dataclasses.asdict(e) for e in events],
        summary=_summarise_skill(events),
        since=since,
        until=until,
        rollbacks=rollbacks,
    )


def render_memory_diff_json(
    events: list[MemoryEvent],
    *,
    since: _dt.datetime,
    until: _dt.datetime,
    rollbacks: list[RollbackMarker] | None = None,
) -> str:
    return _render_json(
        events=[dataclasses.asdict(e) for e in events],
        summary=_summarise_memory(events),
        since=since,
        until=until,
        rollbacks=rollbacks,
    )


def _render_json(
    *,
    events: list[dict[str, Any]],
    summary: dict[str, int],
    since: _dt.datetime,
    until: _dt.datetime,
    rollbacks: list[RollbackMarker] | None,
) -> str:
    payload = {
        "since": since.isoformat() + "Z",
        "until": until.isoformat() + "Z",
        "events": events,
        "rollbacks": [dataclasses.asdict(r) for r in (rollbacks or [])],
        "summary": summary,
    }
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _iter_mutation_records(
    audit_dir: Path,
    *,
    since: _dt.datetime,
    until: _dt.datetime,
):
    """Walk every ``mutations-YYYY-MM.jsonl`` under ``audit_dir`` and
    yield records whose ``timestamp`` falls in the window."""
    if not audit_dir.exists():
        return
    for log_path in sorted(audit_dir.glob("mutations-*.jsonl")):
        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            ts_str = str(rec.get("timestamp") or "")
            if not _in_window(ts_str, since, until):
                continue
            yield rec


def _in_window(ts_str: str, since: _dt.datetime, until: _dt.datetime) -> bool:
    if not ts_str:
        return False
    try:
        ts = _parse_iso_naive(ts_str)
    except ValueError:
        return False
    return since <= ts <= until


def _parse_iso_naive(s: str) -> _dt.datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return dt


def _or_none(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _extract_skill_name(path: str) -> str:
    """``…/skills/<name>/skill.md`` (or SKILL.md) → ``<name>``.
    Falls back to the file basename if the path layout is
    unfamiliar."""
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part == "skills" and i + 1 < len(parts):
            return parts[i + 1]
    return Path(path).name or "?"


def _extract_memory_name(path: str) -> str:
    """``…/memory/<name>.md`` → ``<name>``."""
    p = Path(path)
    if p.suffix == ".md":
        return p.stem
    return p.name or "?"
