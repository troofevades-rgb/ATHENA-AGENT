"""Tests for archive_skill / unarchive_skill."""
from __future__ import annotations

from pathlib import Path

import pytest

from ocode.skills import archive
from ocode.skills.archive import SkillNotFoundError, archive_skill, unarchive_skill
from ocode.skills.discovery import discover_skills
from ocode.skills.frontmatter import parse_frontmatter


def test_skill_delete_moves_to_archive(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "to-archive")

    archived = archive_skill("to-archive")
    assert archived.parent.name == ".archive"
    assert not (user_skills / "to-archive").exists()

    fm, _ = parse_frontmatter(archived / "SKILL.md")
    assert fm.state == "archived"


def test_skill_unarchive_restores(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "round")
    archive_skill("round")

    restored = unarchive_skill("round")
    assert restored.parent == user_skills
    fm, _ = parse_frontmatter(restored / "SKILL.md")
    assert fm.state == "active"


def test_archive_collision_renames(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    archive_dir = user_skills / ".archive"
    archive_dir.mkdir()

    write_skill(archive_dir, "collide", state="archived")
    write_skill(user_skills, "collide")

    new_path = archive_skill("collide")
    assert new_path.name == "collide-1"
    # Both archived copies exist
    assert (archive_dir / "collide").exists()
    assert (archive_dir / "collide-1").exists()


def test_archive_missing_skill_raises(isolated_home: Path) -> None:
    (isolated_home / ".ocode" / "skills").mkdir(parents=True)
    with pytest.raises(SkillNotFoundError):
        archive_skill("nope")


def test_unarchive_non_archived_raises(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "active-skill")
    with pytest.raises(SkillNotFoundError, match="not archived"):
        unarchive_skill("active-skill")
