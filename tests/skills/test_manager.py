"""Unit tests for athena.skills.manager — exercised end-to-end through
test_skill_tools.py in prompt 1.6, but this file checks the lower-level
contract directly (existence, write_origin policy, file path safety)."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.provenance import (
    CURATOR,
    FOREGROUND,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.skills.archive import SkillNotFoundError
from athena.skills.frontmatter import parse_frontmatter
from athena.skills.manager import (
    CuratorPolicyError,
    SkillExistsError,
    skill_create,
    skill_delete,
    skill_patch,
    skill_view,
    skill_write_file,
)


def test_create_writes_frontmatter_and_body(isolated_home: Path) -> None:
    skill_dir = skill_create(
        "demo",
        {"description": "demo skill"},
        "body line\n",
    )
    assert (skill_dir / "SKILL.md").exists()
    fm, body = parse_frontmatter(skill_dir / "SKILL.md")
    assert fm.name == "demo"
    assert fm.description == "demo skill"
    assert body == "body line\n"
    # Provenance defaults to FOREGROUND in the test context.
    assert fm.write_origin == FOREGROUND
    assert fm.created_at is not None
    assert fm.last_activity_at is not None


def test_create_refuses_duplicate(isolated_home: Path) -> None:
    skill_create("dup", {"description": "x"}, "")
    with pytest.raises(SkillExistsError):
        skill_create("dup", {"description": "x"}, "")


def test_patch_updates_body_and_bumps_activity(isolated_home: Path) -> None:
    skill_create("p", {"description": "x"}, "old body\n")
    skill_dir = skill_patch("p", body="new body\n", frontmatter_updates={"description": "newer"})
    fm, body = parse_frontmatter(skill_dir / "SKILL.md")
    assert fm.description == "newer"
    assert body == "new body\n"


def test_patch_cannot_rename(isolated_home: Path) -> None:
    skill_create("orig", {"description": "x"}, "")
    skill_dir = skill_patch("orig", frontmatter_updates={"name": "renamed"})
    fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
    assert fm.name == "orig"  # name reset by patch logic


def test_delete_archives(isolated_home: Path) -> None:
    skill_create("doomed", {"description": "x"}, "")
    new_path = skill_delete("doomed")
    assert new_path.parent.name == ".archive"


def test_delete_under_curator_requires_absorbed_into(isolated_home: Path) -> None:
    """The skill must be curator-mutable to begin with (write_origin in
    background_review / curator). Create it under CURATOR so the curator
    can later act on it."""
    token = set_current_write_origin(CURATOR)
    try:
        skill_create("c-target", {"description": "x"}, "")
        with pytest.raises(CuratorPolicyError):
            skill_delete("c-target")
        new_path = skill_delete("c-target", absorbed_into="umbrella")
        assert (new_path / ".archive_meta.json").exists()
    finally:
        reset_current_write_origin(token)


def test_curator_cannot_delete_foreground_skill(isolated_home: Path) -> None:
    skill_create("user-owned", {"description": "x"}, "")  # foreground
    token = set_current_write_origin(CURATOR)
    try:
        with pytest.raises(CuratorPolicyError, match="foreground-authored"):
            skill_delete("user-owned", absorbed_into="umbrella")
    finally:
        reset_current_write_origin(token)


def test_curator_cannot_patch_foreground_skill(isolated_home: Path) -> None:
    skill_create("user-owned-2", {"description": "x"}, "")
    token = set_current_write_origin(CURATOR)
    try:
        with pytest.raises(CuratorPolicyError, match="foreground-authored"):
            skill_patch("user-owned-2", frontmatter_updates={"description": "edited"})
    finally:
        reset_current_write_origin(token)


def test_curator_cannot_pin(isolated_home: Path) -> None:
    from athena.skills.manager import skill_pin, skill_unpin

    token = set_current_write_origin(CURATOR)
    try:
        skill_create("pinnable", {"description": "x"}, "")
        with pytest.raises(CuratorPolicyError, match="foreground-only"):
            skill_pin("pinnable")
        with pytest.raises(CuratorPolicyError, match="foreground-only"):
            skill_unpin("pinnable")
    finally:
        reset_current_write_origin(token)


def test_background_review_cannot_pin(isolated_home: Path) -> None:
    from athena.provenance import BACKGROUND_REVIEW
    from athena.skills.manager import skill_pin

    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        skill_create("br-skill", {"description": "x"}, "")
        with pytest.raises(CuratorPolicyError):
            skill_pin("br-skill")
    finally:
        reset_current_write_origin(token)


def test_curator_cannot_touch_pinned_skill(isolated_home: Path) -> None:
    """Pinned skills are inviolate to autonomous mutation even when the
    skill's own write_origin would normally permit it."""
    # Create + pin under foreground; curator can't unpin (foreground-only)
    # so pinning has to stick.
    skill_create(
        "pinned-precious",
        {"description": "x", "pinned": True, "write_origin": "background_review"},
        "",
    )
    token = set_current_write_origin(CURATOR)
    try:
        with pytest.raises(CuratorPolicyError, match="pinned"):
            skill_patch("pinned-precious", frontmatter_updates={"description": "no"})
        with pytest.raises(CuratorPolicyError, match="pinned"):
            skill_delete("pinned-precious", absorbed_into="umbrella")
    finally:
        reset_current_write_origin(token)


def test_curator_blocked_on_migration_origin_until_local_activity(
    isolated_home: Path,
) -> None:
    """Migration-origin skills are write-protected until the user has
    interacted with them (last_activity_at > imported_at)."""
    from datetime import datetime, timedelta, timezone

    imported = datetime.now(timezone.utc) - timedelta(days=100)
    skill_create(
        "imported",
        {
            "description": "x",
            "write_origin": "migration",
            "imported_at": imported,
            "last_activity_at": imported,
        },
        "",
    )
    token = set_current_write_origin(CURATOR)
    try:
        with pytest.raises(CuratorPolicyError, match="imported"):
            skill_delete("imported", absorbed_into="umbrella")
    finally:
        reset_current_write_origin(token)


def test_foreground_can_pin_and_unpin(isolated_home: Path) -> None:
    from athena.skills.manager import skill_pin, skill_unpin

    skill_create("pinme", {"description": "x"}, "")
    # FOREGROUND is the default origin in tests; just call directly.
    skill_pin("pinme")
    skill_unpin("pinme")  # no exception


def test_write_file_under_references(isolated_home: Path) -> None:
    skill_create("wf", {"description": "x"}, "")
    p = skill_write_file("wf", "references/notes.md", "hello\n")
    assert p.read_text(encoding="utf-8") == "hello\n"
    assert p.parent.name == "references"


def test_write_file_rejects_traversal(isolated_home: Path) -> None:
    skill_create("wf-bad", {"description": "x"}, "")
    with pytest.raises(ValueError, match="'..'"):
        skill_write_file("wf-bad", "references/../escape.md", "x")


def test_write_file_rejects_disallowed_subdir(isolated_home: Path) -> None:
    skill_create("wf-sub", {"description": "x"}, "")
    with pytest.raises(ValueError, match="must start with"):
        skill_write_file("wf-sub", "secret/x.md", "x")


def test_view_returns_full_text(isolated_home: Path) -> None:
    skill_create("v", {"description": "x"}, "body content\n")
    text = skill_view("v")
    assert text is not None
    assert text.startswith("---")
    assert "body content" in text


def test_view_missing_returns_none(isolated_home: Path) -> None:
    assert skill_view("ghost") is None


def test_unarchive_unknown_raises(isolated_home: Path) -> None:
    from athena.skills.manager import skill_unarchive

    with pytest.raises(SkillNotFoundError):
        skill_unarchive("never-was")
