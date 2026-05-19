"""Tests for the model-facing skill tools (skills_list, skill_view, skill_manage).

The tools dispatch to athena.skills.manager; these tests exercise the wiring
plus the per-action contract (response shape, error mapping, write_origin
policy from the curator)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.provenance import (
    CURATOR,
    FOREGROUND,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.skills.frontmatter import parse_frontmatter
from athena.tools import file_ops, skill_tools


@pytest.fixture
def workspace_set(isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace-tools"
    ws.mkdir()
    # The skill_tools module reads file_ops._WORKSPACE.
    monkeypatch.setattr(file_ops, "_WORKSPACE", ws)
    return ws


def _parse(response: str) -> dict:
    return json.loads(response)


def test_skills_list_filters_by_state(workspace_set: Path, write_skill) -> None:
    user = Path.home() / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "alive")
    write_skill(user, "stale-one", state="stale")
    archived = user / ".archive"
    archived.mkdir()
    write_skill(archived, "old", state="archived")

    active = skill_tools.skills_list(state="active")
    assert "alive" in active
    assert "stale-one" not in active
    assert "old" not in active

    stale = skill_tools.skills_list(state="stale")
    assert "stale-one" in stale
    assert "alive" not in stale

    all_skills = skill_tools.skills_list(state="all")
    assert "alive" in all_skills and "stale-one" in all_skills and "old" in all_skills


def test_skills_list_filters_by_pinned(workspace_set: Path, write_skill) -> None:
    user = Path.home() / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "p1", pinned=True)
    write_skill(user, "p2", pinned=False)

    pinned = skill_tools.skills_list(pinned=True)
    assert "p1" in pinned and "p2" not in pinned


def test_skill_view_returns_full_body(workspace_set: Path, write_skill) -> None:
    user = Path.home() / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "viewme", body="body content here\n")
    text = skill_tools.skill_view("viewme")
    assert text.startswith("---")
    assert "body content here" in text


def test_skill_view_missing(workspace_set: Path) -> None:
    assert "ERROR" in skill_tools.skill_view("ghost")


def test_skill_manage_create_with_foreground_origin(workspace_set: Path) -> None:
    out = _parse(
        skill_tools.skill_manage(
            action="create",
            name="from-tool",
            frontmatter={"description": "made by tool"},
            body="hi\n",
        )
    )
    assert out["success"] is True
    assert out["action"] == "create"
    skill_md = workspace_set / ".athena" / "skills" / "from-tool" / "SKILL.md"
    assert skill_md.exists()
    fm, _ = parse_frontmatter(skill_md)
    assert fm.write_origin == FOREGROUND


def test_skill_manage_create_duplicate_returns_error(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="dup", frontmatter={"description": "x"})
    out = _parse(
        skill_tools.skill_manage(action="create", name="dup", frontmatter={"description": "x"})
    )
    assert out["success"] is False
    assert "SkillExistsError" in out["message"]


def test_skill_manage_patch_preserves_origin(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="po", frontmatter={"description": "orig"})
    skill_tools.skill_manage(action="patch", name="po", frontmatter={"description": "edited"})
    fm, _ = parse_frontmatter(workspace_set / ".athena" / "skills" / "po" / "SKILL.md")
    assert fm.description == "edited"
    assert fm.write_origin == FOREGROUND


def test_skill_manage_delete_archives(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="bye", frontmatter={"description": "x"})
    out = _parse(skill_tools.skill_manage(action="delete", name="bye"))
    assert out["success"] is True
    assert (workspace_set / ".athena" / "skills" / ".archive" / "bye").exists()


def test_skill_manage_unarchive_restores(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="restore", frontmatter={"description": "x"})
    skill_tools.skill_manage(action="delete", name="restore")
    out = _parse(skill_tools.skill_manage(action="unarchive", name="restore"))
    assert out["success"] is True
    assert (workspace_set / ".athena" / "skills" / "restore").exists()


def test_skill_manage_pin_sets_pinned_true(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="pinning", frontmatter={"description": "x"})
    _parse(skill_tools.skill_manage(action="pin", name="pinning"))
    fm, _ = parse_frontmatter(workspace_set / ".athena" / "skills" / "pinning" / "SKILL.md")
    assert fm.pinned is True


def test_skill_manage_write_file_under_references(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="wf", frontmatter={"description": "x"})
    out = _parse(
        skill_tools.skill_manage(
            action="write_file",
            name="wf",
            file_path="references/notes.md",
            file_content="hi\n",
        )
    )
    assert out["success"] is True
    p = workspace_set / ".athena" / "skills" / "wf" / "references" / "notes.md"
    assert p.read_text(encoding="utf-8") == "hi\n"


def test_skill_manage_write_file_rejects_bad_path(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="wf-bad", frontmatter={"description": "x"})
    out = _parse(
        skill_tools.skill_manage(
            action="write_file",
            name="wf-bad",
            file_path="references/../escape.md",
            file_content="x",
        )
    )
    assert out["success"] is False


def test_skill_manage_curator_delete_requires_absorbed_into(workspace_set: Path) -> None:
    """The curator can only act on skills it (or background_review) authored.
    Create under CURATOR so the curator can later delete it."""
    token = set_current_write_origin(CURATOR)
    try:
        skill_tools.skill_manage(
            action="create", name="curatable", frontmatter={"description": "x"}
        )
        out = _parse(skill_tools.skill_manage(action="delete", name="curatable"))
        assert out["success"] is False
        assert "CuratorPolicyError" in out["message"]

        # With absorbed_into provided, curator may proceed.
        out2 = _parse(
            skill_tools.skill_manage(
                action="delete",
                name="curatable",
                absorbed_into="umbrella-skill",
            )
        )
        assert out2["success"] is True
    finally:
        reset_current_write_origin(token)


def test_skill_manage_curator_cannot_patch_foreground_skill(workspace_set: Path) -> None:
    """Foreground-authored skills are inviolate to autonomous origins."""
    skill_tools.skill_manage(
        action="create", name="user-skill", frontmatter={"description": "x"}
    )  # foreground
    token = set_current_write_origin(CURATOR)
    try:
        out = _parse(
            skill_tools.skill_manage(
                action="patch",
                name="user-skill",
                frontmatter={"description": "curator wants this"},
            )
        )
        assert out["success"] is False
        assert "foreground-authored" in out["message"]
    finally:
        reset_current_write_origin(token)


def test_skill_manage_curator_cannot_pin(workspace_set: Path) -> None:
    token = set_current_write_origin(CURATOR)
    try:
        skill_tools.skill_manage(
            action="create", name="cur-skill", frontmatter={"description": "x"}
        )
        out = _parse(skill_tools.skill_manage(action="pin", name="cur-skill"))
        assert out["success"] is False
        assert "foreground-only" in out["message"]
    finally:
        reset_current_write_origin(token)


def test_skill_manage_background_review_cannot_pin(workspace_set: Path) -> None:
    from athena.provenance import BACKGROUND_REVIEW

    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        skill_tools.skill_manage(action="create", name="br-skill", frontmatter={"description": "x"})
        out = _parse(skill_tools.skill_manage(action="pin", name="br-skill"))
        assert out["success"] is False
        assert "foreground-only" in out["message"]
    finally:
        reset_current_write_origin(token)


def test_skill_manage_foreground_can_do_anything(workspace_set: Path) -> None:
    skill_tools.skill_manage(action="create", name="multi", frontmatter={"description": "x"})
    # create, patch, pin, unpin, delete — all succeed under foreground.
    out = _parse(
        skill_tools.skill_manage(
            action="patch", name="multi", frontmatter={"description": "edited"}
        )
    )
    assert out["success"] is True
    out = _parse(skill_tools.skill_manage(action="pin", name="multi"))
    assert out["success"] is True
    out = _parse(skill_tools.skill_manage(action="unpin", name="multi"))
    assert out["success"] is True
    out = _parse(skill_tools.skill_manage(action="delete", name="multi"))
    assert out["success"] is True


def test_skill_manage_curator_cannot_delete_migration_origin(
    workspace_set: Path, write_skill
) -> None:
    """Migration-origin skills are write-protected against curator deletion
    until they have local activity newer than imported_at — Phase 1 invariant
    7. (For now we assert the curator policy error path; tighter enforcement
    on migration-origin specifically is checked by the state machine.)"""
    user = workspace_set / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "imported", write_origin="migration")

    token = set_current_write_origin(CURATOR)
    try:
        # Even with absorbed_into the curator policy must require an explicit
        # opt-in. We accept either behavior: success with absorbed_into is
        # permitted today, but absent absorbed_into must always be denied.
        out = _parse(skill_tools.skill_manage(action="delete", name="imported"))
        assert out["success"] is False
    finally:
        reset_current_write_origin(token)


def test_skill_manage_unknown_action(workspace_set: Path) -> None:
    out = _parse(skill_tools.skill_manage(action="explode", name="x"))
    assert out["success"] is False
    assert "unknown action" in out["message"]
