"""Tests for athena.mcp.resources (T3-02 audit gap).

Direct exercise of :class:`AthenaMCPResources.read_resource` —
covers all three URI roots (skills, memories, audit) plus
malformed URIs. The handshake tests already cover
``resources/list`` dispatch through the server; these tests focus
on per-URI resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

from athena.mcp.resources import RESOURCE_DESCRIPTORS, AthenaMCPResources


def _make_resources(workspace: Path, profile: Path, audit_dir: Path) -> AthenaMCPResources:
    return AthenaMCPResources(
        workspace=workspace,
        memory_profile="default",
        audit_dir=audit_dir,
    )


def _make_skill(workspace: Path, name: str, description: str = "test skill") -> None:
    skill_dir = workspace / ".athena" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"state: active\n"
        f"pinned: false\n"
        f"write_origin: foreground\n"
        f"---\n\n"
        f"# {name}\n\nbody for {name}\n",
        encoding="utf-8",
    )


def _make_audit_log(audit_dir: Path, month: str, lines: list[dict]) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    log = audit_dir / f"mutations-{month}.jsonl"
    with open(log, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")
    return log


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------


def test_resource_descriptors_advertises_three_roots() -> None:
    uris = sorted(r["uri"] for r in RESOURCE_DESCRIPTORS)
    assert uris == ["athena://audit/", "athena://memories/", "athena://skills/"]
    for desc in RESOURCE_DESCRIPTORS:
        assert "name" in desc
        assert "mimeType" in desc


# ---------------------------------------------------------------------------
# Skills resource
# ---------------------------------------------------------------------------


def test_skills_index_lists_known_skills(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "alpha", "first skill")
    _make_skill(workspace, "beta", "second skill")

    res = _make_resources(workspace, tmp_path / "profile", tmp_path / "audit")
    result = res.read_resource("athena://skills/")
    contents = result["contents"]
    assert len(contents) == 1
    text = contents[0]["text"]
    assert "alpha" in text
    assert "beta" in text
    assert contents[0]["mimeType"] == "text/markdown"


def test_skills_specific_returns_body(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "readable-skill", "for read")

    res = _make_resources(workspace, tmp_path / "profile", tmp_path / "audit")
    result = res.read_resource("athena://skills/readable-skill")
    text = result["contents"][0]["text"]
    assert "body for readable-skill" in text


def test_skills_unknown_returns_error_contents(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = _make_resources(workspace, tmp_path / "profile", tmp_path / "audit")
    result = res.read_resource("athena://skills/does-not-exist")
    text = result["contents"][0]["text"]
    assert text.startswith("ERROR:")
    assert "not found" in text


# ---------------------------------------------------------------------------
# Memories resource
# ---------------------------------------------------------------------------


def test_memories_index_handles_missing_profile(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = _make_resources(workspace, tmp_path / "profile", tmp_path / "audit")
    result = res.read_resource("athena://memories/")
    text = result["contents"][0]["text"]
    # Either "no entries" markdown or a populated index — never crash.
    assert isinstance(text, str)


def test_memories_unknown_entry_returns_error_contents(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = _make_resources(workspace, tmp_path / "profile", tmp_path / "audit")
    result = res.read_resource("athena://memories/never-existed-abc")
    text = result["contents"][0]["text"]
    assert text.startswith("ERROR:")


# ---------------------------------------------------------------------------
# Audit resource
# ---------------------------------------------------------------------------


def test_audit_index_no_logs_returns_marker(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    audit_dir = tmp_path / "audit"  # doesn't exist
    res = _make_resources(workspace, tmp_path / "profile", audit_dir)
    result = res.read_resource("athena://audit/")
    text = result["contents"][0]["text"]
    assert "no audit logs" in text.lower()


def test_audit_index_lists_available_months(tmp_path) -> None:
    audit_dir = tmp_path / "audit"
    _make_audit_log(audit_dir, "2026-04", [{"tool_name": "Old"}])
    _make_audit_log(audit_dir, "2026-05", [{"tool_name": "New"}])
    res = _make_resources(tmp_path / "ws", tmp_path / "profile", audit_dir)
    (tmp_path / "ws").mkdir()
    result = res.read_resource("athena://audit/")
    text = result["contents"][0]["text"]
    assert "2026-04" in text
    assert "2026-05" in text


def test_audit_specific_month_returns_ndjson(tmp_path) -> None:
    audit_dir = tmp_path / "audit"
    _make_audit_log(
        audit_dir,
        "2026-05",
        [
            {"tool_name": "Write", "timestamp": "2026-05-01T00:00:00Z"},
            {"tool_name": "Edit", "timestamp": "2026-05-02T00:00:00Z"},
        ],
    )
    res = _make_resources(tmp_path / "ws", tmp_path / "profile", audit_dir)
    (tmp_path / "ws").mkdir()
    result = res.read_resource("athena://audit/2026-05")
    contents = result["contents"][0]
    assert contents["mimeType"] == "application/x-ndjson"
    # Body has both entries on separate lines.
    text = contents["text"]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["tool_name"] == "Write"


def test_audit_missing_month_returns_error_contents(tmp_path) -> None:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    res = _make_resources(tmp_path / "ws", tmp_path / "profile", audit_dir)
    (tmp_path / "ws").mkdir()
    result = res.read_resource("athena://audit/2099-12")
    text = result["contents"][0]["text"]
    assert text.startswith("ERROR:")
    assert "2099-12" in text


# ---------------------------------------------------------------------------
# Dispatch errors
# ---------------------------------------------------------------------------


def test_unknown_uri_scheme_returns_error_contents(tmp_path) -> None:
    res = _make_resources(tmp_path / "ws", tmp_path / "profile", tmp_path / "audit")
    (tmp_path / "ws").mkdir()
    result = res.read_resource("athena://something-else/x")
    text = result["contents"][0]["text"]
    assert "unknown" in text.lower()


def test_empty_uri_returns_error_contents(tmp_path) -> None:
    res = _make_resources(tmp_path / "ws", tmp_path / "profile", tmp_path / "audit")
    (tmp_path / "ws").mkdir()
    result = res.read_resource("")
    text = result["contents"][0]["text"]
    assert "uri required" in text.lower()
