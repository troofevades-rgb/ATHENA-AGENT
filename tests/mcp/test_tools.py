"""Tests for athena.mcp.tools — the 7 curated tools (T3-02.8).

Happy + error path for each tool. Skills/memory rely on the actual
athena.skills.* / athena.memory.store helpers; tests build small
fixtures rather than monkeypatching, so the tests double as
integration coverage for the tools→athena adapter layer.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(workspace: Path, name: str, description: str = "test skill") -> None:
    """Write a skill into the workspace's .athena/skills/<name>/ dir
    with valid frontmatter so discover_skills picks it up."""
    skill_dir = workspace / ".athena" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"state: active\n"
        f"pinned: false\n"
        f"write_origin: foreground\n"
        f"---\n"
        f"\n"
        f"skill body for {name}\n"
    )
    (skill_dir / "skill.md").write_text(body, encoding="utf-8")


def _make_audit_record(audit_dir: Path, **overrides) -> dict:
    rec = {
        "timestamp": "2026-05-01T12:00:00+00:00",
        "write_origin": "foreground",
        "session_id": "s1",
        "parent_session_id": None,
        "tool_name": "Write",
        "tool_call_id": "tc1",
        "path": "/tmp/x.txt",
        "snapshot_id": "snap-1",
        "sha_before": None,
        "sha_after": "abc",
        "byte_delta": 10,
    }
    rec.update(overrides)
    log = audit_dir / "mutations-2026-05.jsonl"
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


# ---------------------------------------------------------------------------
# Snapshot / rollback
# ---------------------------------------------------------------------------


def test_snapshot_files_happy_path(mcp_tools, tmp_path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")
    result = mcp_tools.call_tool("athena_snapshot_files", {"paths": [str(target)], "label": "test"})
    text = result["content"][0]["text"]
    assert "snapshot_id" in text
    assert "test" in text  # label echoed
    assert "isError" not in result


def test_snapshot_files_missing_path_errors(mcp_tools, tmp_path) -> None:
    result = mcp_tools.call_tool("athena_snapshot_files", {"paths": [str(tmp_path / "nope.txt")]})
    assert result.get("isError") is True
    assert "do not exist" in result["content"][0]["text"]


def test_snapshot_files_empty_paths_errors(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_snapshot_files", {"paths": []})
    assert result.get("isError") is True


def test_rollback_files_unknown_snapshot_errors(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_rollback_files", {"snapshot_id": "nonexistent-snap"})
    assert result.get("isError") is True
    assert "not found" in result["content"][0]["text"]


def test_rollback_files_restores_after_snapshot(mcp_tools, tmp_path) -> None:
    """End-to-end: snapshot a file, mutate it, rollback, verify."""
    target = tmp_path / "rollback-target.txt"
    target.write_text("original content", encoding="utf-8")

    snap_result = mcp_tools.call_tool("athena_snapshot_files", {"paths": [str(target)]})
    snap_text = snap_result["content"][0]["text"]
    snap_id = next(
        line.split(": ", 1)[1].strip()
        for line in snap_text.splitlines()
        if line.startswith("snapshot_id:")
    )

    # Mutate.
    target.write_text("modified content", encoding="utf-8")

    rb_result = mcp_tools.call_tool("athena_rollback_files", {"snapshot_id": snap_id})
    assert rb_result.get("isError") is None or rb_result.get("isError") is False
    assert "restored" in rb_result["content"][0]["text"]
    # File restored.
    assert target.read_text(encoding="utf-8") == "original content"


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def test_list_skills_finds_skill(mcp_tools, workspace) -> None:
    _make_skill(workspace, "test-skill-one", "first skill")
    _make_skill(workspace, "test-skill-two", "second skill")
    result = mcp_tools.call_tool("athena_list_skills", {})
    text = result["content"][0]["text"]
    assert "test-skill-one" in text
    assert "test-skill-two" in text


def test_list_skills_empty_workspace(mcp_tools, workspace) -> None:
    result = mcp_tools.call_tool("athena_list_skills", {})
    text = result["content"][0]["text"]
    # discover_skills walks the user-level dir too; just confirm no
    # crash. If user dir is empty, expect "no skills found".
    assert isinstance(text, str)


def test_read_skill_happy(mcp_tools, workspace) -> None:
    _make_skill(workspace, "readable-skill", "for read test")
    result = mcp_tools.call_tool("athena_read_skill", {"name": "readable-skill"})
    text = result["content"][0]["text"]
    assert "skill body for readable-skill" in text


def test_read_skill_missing_errors(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_read_skill", {"name": "nonexistent_skill_for_test"})
    assert result.get("isError") is True


def test_read_skill_no_name_errors(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_read_skill", {"name": ""})
    assert result.get("isError") is True


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def test_list_memories_handles_missing_profile(mcp_tools) -> None:
    """Profile that has never been written to → returns 'no entries'
    rather than crashing."""
    result = mcp_tools.call_tool(
        "athena_list_memories", {"profile": "test-profile-never-existed-abc123"}
    )
    text = result["content"][0]["text"]
    assert "no memory entries" in text or "memory entries" in text


def test_read_memory_no_name_errors(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_read_memory", {"name": ""})
    assert result.get("isError") is True


def test_read_memory_nonexistent_errors(mcp_tools) -> None:
    result = mcp_tools.call_tool(
        "athena_read_memory",
        {"name": "absolutely-nonexistent-memory-entry-xyz", "profile": "test"},
    )
    assert result.get("isError") is True


# ---------------------------------------------------------------------------
# Audit query
# ---------------------------------------------------------------------------


def test_audit_query_no_records(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_audit_query", {})
    text = result["content"][0]["text"]
    assert "no audit records" in text


def test_audit_query_returns_records(mcp_tools, audit_dir) -> None:
    _make_audit_record(audit_dir, tool_name="Write")
    _make_audit_record(audit_dir, tool_name="Edit", timestamp="2026-05-02T12:00:00+00:00")
    result = mcp_tools.call_tool("athena_audit_query", {"limit": 10})
    text = result["content"][0]["text"]
    assert "audit records" in text
    assert "Write" in text
    assert "Edit" in text


def test_audit_query_filter_by_tool_name(mcp_tools, audit_dir) -> None:
    _make_audit_record(audit_dir, tool_name="Write")
    _make_audit_record(audit_dir, tool_name="Edit", timestamp="2026-05-02T12:00:00+00:00")
    result = mcp_tools.call_tool("athena_audit_query", {"tool_name": "Write"})
    text = result["content"][0]["text"]
    assert "Write" in text
    assert "Edit" not in text


def test_audit_query_filter_by_since(mcp_tools, audit_dir) -> None:
    _make_audit_record(audit_dir, tool_name="Old", timestamp="2026-04-01T00:00:00+00:00")
    _make_audit_record(audit_dir, tool_name="New", timestamp="2026-06-01T00:00:00+00:00")
    result = mcp_tools.call_tool("athena_audit_query", {"since": "2026-05-01T00:00:00+00:00"})
    text = result["content"][0]["text"]
    assert "New" in text
    assert "Old" not in text


def test_audit_query_filter_by_write_origin(mcp_tools, audit_dir) -> None:
    _make_audit_record(audit_dir, write_origin="foreground")
    _make_audit_record(
        audit_dir,
        write_origin="curator",
        timestamp="2026-05-02T12:00:00+00:00",
    )
    result = mcp_tools.call_tool("athena_audit_query", {"write_origin": "curator"})
    text = result["content"][0]["text"]
    assert "curator" in text
    assert text.count("foreground") == 0


# ---------------------------------------------------------------------------
# Dispatch error paths
# ---------------------------------------------------------------------------


def test_unknown_tool_returns_error(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_definitely_not_a_tool", {})
    assert result.get("isError") is True
    assert "unknown tool" in result["content"][0]["text"]


def test_invalid_arguments_typeerror_handled(mcp_tools) -> None:
    result = mcp_tools.call_tool("athena_snapshot_files", {"not_a_real_arg": True})
    # snapshot_files requires 'paths'; TypeError gets converted.
    assert result.get("isError") is True
