"""Tests for athena.audit.diff (T3-04)."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from athena.audit.diff import (
    MEMORY_TOOL_NAMES,
    SKILL_TOOL_NAMES,
    collect_memory_events,
    collect_rollback_markers,
    collect_skill_events,
    render_memory_diff,
    render_memory_diff_json,
    render_skill_diff,
    render_skill_diff_json,
)

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _write_mutation(
    audit_dir: Path,
    *,
    month: str = "2026-05",
    timestamp: str = "2026-05-15T10:00:00Z",
    tool_name: str = "skill_create",
    path: str = "/skills/alpha/skill.md",
    write_origin: str = "foreground",
    sha_before: str | None = None,
    sha_after: str | None = "abc123",
    byte_delta: int = 42,
    snapshot_id: str | None = "snap-1",
    session_id: str | None = "s1",
) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    log = audit_dir / f"mutations-{month}.jsonl"
    rec = {
        "timestamp": timestamp,
        "write_origin": write_origin,
        "session_id": session_id,
        "parent_session_id": None,
        "tool_name": tool_name,
        "tool_call_id": "tc1",
        "path": path,
        "snapshot_id": snapshot_id,
        "sha_before": sha_before,
        "sha_after": sha_after,
        "byte_delta": byte_delta,
    }
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _write_checkpoint_audit(
    profile_dir: Path,
    *,
    session: str = "s1",
    ts: str = "2026-05-15T11:00:00Z",
    event_type: str = "checkpoint",
    summary: str = "Checkpoint 'work' created",
    data: dict | None = None,
) -> None:
    ckpt_dir = profile_dir / "checkpoints" / session
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    log = ckpt_dir / "audit.jsonl"
    entry = {
        "ts": ts,
        "event_type": event_type,
        "summary": summary,
        "data": data or {},
    }
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


SINCE = _dt.datetime(2026, 5, 1)
UNTIL = _dt.datetime(2026, 5, 31)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_skill_tool_names_includes_expected() -> None:
    assert "skill_create" in SKILL_TOOL_NAMES
    assert "skill_patch" in SKILL_TOOL_NAMES
    assert "skill_delete" in SKILL_TOOL_NAMES


def test_memory_tool_names_includes_expected() -> None:
    assert "memory_write" in MEMORY_TOOL_NAMES
    assert "memory_delete" in MEMORY_TOOL_NAMES


# ---------------------------------------------------------------------------
# collect_skill_events
# ---------------------------------------------------------------------------


def test_collect_skill_events_returns_skill_only(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="skill_create", path="/skills/alpha/skill.md")
    _write_mutation(
        audit,
        tool_name="memory_write",
        path="/profile/memory/foo.md",
        timestamp="2026-05-15T10:01:00Z",
    )
    _write_mutation(
        audit,
        tool_name="Write",  # unrelated mutation
        path="/some/file.py",
        timestamp="2026-05-15T10:02:00Z",
    )
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    assert len(events) == 1
    assert events[0].skill_name == "alpha"
    assert events[0].tool_name == "skill_create"


def test_collect_skill_events_filters_by_actor(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="skill_create", write_origin="foreground")
    _write_mutation(
        audit,
        tool_name="skill_patch",
        write_origin="curator",
        timestamp="2026-05-15T10:01:00Z",
    )
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL, actor="curator")
    assert len(events) == 1
    assert events[0].write_origin == "curator"


def test_collect_skill_events_respects_window(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, timestamp="2026-04-01T00:00:00Z", tool_name="skill_create")
    _write_mutation(audit, timestamp="2026-05-15T00:00:00Z", tool_name="skill_create")
    events = collect_skill_events(
        audit_dir=audit,
        since=_dt.datetime(2026, 5, 1),
        until=_dt.datetime(2026, 6, 1),
    )
    assert len(events) == 1
    assert events[0].timestamp == "2026-05-15T00:00:00Z"


def test_collect_skill_events_sorted_oldest_first(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, timestamp="2026-05-20T00:00:00Z")
    _write_mutation(audit, timestamp="2026-05-10T00:00:00Z")
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    assert [e.timestamp for e in events] == [
        "2026-05-10T00:00:00Z",
        "2026-05-20T00:00:00Z",
    ]


def test_collect_skill_events_categorises(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="skill_create")
    _write_mutation(audit, tool_name="skill_patch", timestamp="2026-05-15T10:01:00Z")
    _write_mutation(audit, tool_name="skill_delete", timestamp="2026-05-15T10:02:00Z")
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    cats = [e.category for e in events]
    assert cats == ["added", "modified", "removed"]


def test_collect_skill_events_extracts_name_from_path(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, path="/home/u/.athena/skills/build-pipeline/skill.md")
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    assert events[0].skill_name == "build-pipeline"


# ---------------------------------------------------------------------------
# collect_memory_events
# ---------------------------------------------------------------------------


def test_collect_memory_events_returns_memory_only(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="memory_write", path="/profile/memory/note.md")
    _write_mutation(
        audit,
        tool_name="skill_create",
        timestamp="2026-05-15T10:01:00Z",
    )
    events = collect_memory_events(audit_dir=audit, since=SINCE, until=UNTIL)
    assert len(events) == 1
    assert events[0].memory_name == "note"


def test_collect_memory_events_categorises(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    # First write (sha_before is None) → added
    _write_mutation(audit, tool_name="memory_write", sha_before=None, sha_after="abc")
    # Subsequent write (sha_before exists) → modified
    _write_mutation(
        audit,
        tool_name="memory_write",
        sha_before="abc",
        sha_after="def",
        timestamp="2026-05-15T10:01:00Z",
    )
    # Delete
    _write_mutation(
        audit,
        tool_name="memory_delete",
        sha_before="def",
        sha_after=None,
        timestamp="2026-05-15T10:02:00Z",
    )
    events = collect_memory_events(audit_dir=audit, since=SINCE, until=UNTIL)
    cats = [e.category for e in events]
    assert cats == ["added", "modified", "removed"]


# ---------------------------------------------------------------------------
# collect_rollback_markers
# ---------------------------------------------------------------------------


def test_collect_rollback_markers_empty(tmp_path: Path) -> None:
    out = collect_rollback_markers(profile_dir=tmp_path, since=SINCE, until=UNTIL)
    assert out == []


def test_collect_rollback_markers_returns_both_types(tmp_path: Path) -> None:
    _write_checkpoint_audit(
        tmp_path,
        ts="2026-05-15T11:00:00Z",
        event_type="checkpoint",
        summary="before refactor",
    )
    _write_checkpoint_audit(
        tmp_path,
        ts="2026-05-15T12:00:00Z",
        event_type="rollback",
        summary="rolled back to before refactor",
    )
    markers = collect_rollback_markers(profile_dir=tmp_path, since=SINCE, until=UNTIL)
    assert len(markers) == 2
    assert {m.event_type for m in markers} == {"checkpoint", "rollback"}


def test_collect_rollback_markers_respects_window(tmp_path: Path) -> None:
    _write_checkpoint_audit(tmp_path, ts="2026-04-01T00:00:00Z", event_type="checkpoint")
    _write_checkpoint_audit(tmp_path, ts="2026-05-15T00:00:00Z", event_type="rollback")
    markers = collect_rollback_markers(
        profile_dir=tmp_path,
        since=_dt.datetime(2026, 5, 1),
        until=_dt.datetime(2026, 6, 1),
    )
    assert len(markers) == 1
    assert markers[0].event_type == "rollback"


# ---------------------------------------------------------------------------
# Human-readable rendering
# ---------------------------------------------------------------------------


def test_render_skill_diff_empty() -> None:
    out = render_skill_diff([], since=SINCE, until=UNTIL)
    assert "(no changes)" in out


def test_render_skill_diff_lists_events(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(
        audit,
        tool_name="skill_create",
        path="/skills/alpha/skill.md",
        sha_before=None,
        sha_after="abc",
        byte_delta=100,
    )
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    out = render_skill_diff(events, since=SINCE, until=UNTIL)
    assert "Created: alpha" in out
    assert "foreground" in out
    assert "skill_create" in out
    assert "(+100 bytes)" in out
    assert "[content not in audit log" in out
    assert "1 added" in out


def test_render_skill_diff_includes_rollback_markers(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="skill_patch")
    _write_checkpoint_audit(
        tmp_path,
        ts="2026-05-15T11:00:00Z",
        event_type="rollback",
        summary="rolled back to checkpoint x",
    )
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    rollbacks = collect_rollback_markers(profile_dir=tmp_path, since=SINCE, until=UNTIL)
    out = render_skill_diff(events, since=SINCE, until=UNTIL, rollbacks=rollbacks)
    assert "Rollback / checkpoint events" in out
    assert "rolled back to checkpoint x" in out


def test_render_memory_diff_lists_events(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(
        audit,
        tool_name="memory_write",
        path="/profile/memory/note.md",
        sha_before=None,
        sha_after="abc",
    )
    events = collect_memory_events(audit_dir=audit, since=SINCE, until=UNTIL)
    out = render_memory_diff(events, since=SINCE, until=UNTIL)
    assert "Added: note" in out


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def test_render_skill_diff_json_schema(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="skill_create")
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    payload = json.loads(render_skill_diff_json(events, since=SINCE, until=UNTIL))
    assert set(payload.keys()) == {"since", "until", "events", "rollbacks", "summary"}
    assert payload["summary"] == {"added": 1, "modified": 0, "removed": 0}
    assert payload["events"][0]["tool_name"] == "skill_create"


def test_render_memory_diff_json_schema(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="memory_write", path="/profile/memory/x.md")
    events = collect_memory_events(audit_dir=audit, since=SINCE, until=UNTIL)
    payload = json.loads(render_memory_diff_json(events, since=SINCE, until=UNTIL))
    assert payload["summary"] == {"added": 1, "modified": 0, "removed": 0}
    assert payload["events"][0]["memory_name"] == "x"
    assert payload["events"][0]["tool_name"] == "memory_write"


def test_render_skill_diff_json_includes_rollbacks(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _write_mutation(audit, tool_name="skill_create")
    _write_checkpoint_audit(
        tmp_path,
        ts="2026-05-15T11:00:00Z",
        event_type="checkpoint",
        summary="cp",
        data={"id": "cp-1"},
    )
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    rollbacks = collect_rollback_markers(profile_dir=tmp_path, since=SINCE, until=UNTIL)
    payload = json.loads(
        render_skill_diff_json(events, since=SINCE, until=UNTIL, rollbacks=rollbacks)
    )
    assert len(payload["rollbacks"]) == 1
    assert payload["rollbacks"][0]["event_type"] == "checkpoint"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_missing_audit_dir_returns_empty(tmp_path: Path) -> None:
    out = collect_skill_events(
        audit_dir=tmp_path / "does-not-exist",
        since=SINCE,
        until=UNTIL,
    )
    assert out == []


def test_malformed_jsonl_lines_skipped(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    log = audit / "mutations-2026-05.jsonl"
    log.write_text(
        "this is not json\n"
        + json.dumps(
            {
                "timestamp": "2026-05-15T10:00:00Z",
                "tool_name": "skill_create",
                "path": "/skills/x/skill.md",
                "write_origin": "foreground",
                "sha_after": "abc",
                "byte_delta": 1,
                "snapshot_id": "s",
            }
        )
        + "\n"
        + "\n"  # blank line
        + '{"missing":"timestamp"}'
        + "\n",
        encoding="utf-8",
    )
    events = collect_skill_events(audit_dir=audit, since=SINCE, until=UNTIL)
    # Only the valid line survived; the malformed and missing-ts lines were
    # silently dropped.
    assert len(events) == 1
