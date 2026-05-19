"""Tests for pin_skill / unpin_skill."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from athena.skills.archive import SkillNotFoundError
from athena.skills.frontmatter import parse_frontmatter
from athena.skills.pin import pin_skill, unpin_skill
from athena.skills.state_machine import apply_transitions


def test_pin_and_unpin(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    skill_dir = write_skill(user_skills, "pinme")

    pin_skill("pinme")
    fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
    assert fm.pinned is True

    unpin_skill("pinme")
    fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
    assert fm.pinned is False


def test_pin_idempotent(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    skill_dir = write_skill(user_skills, "twice")

    pin_skill("twice")
    after_first = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    pin_skill("twice")
    after_second = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert after_first == after_second


def test_pin_unknown_raises(isolated_home: Path) -> None:
    (isolated_home / ".athena" / "skills").mkdir(parents=True)
    with pytest.raises(SkillNotFoundError):
        pin_skill("ghost")


def test_pinned_skill_skips_state_transitions(isolated_home: Path, write_skill) -> None:
    """A pinned skill that is *very* stale must not be archived or marked stale."""
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    long_ago = datetime.now(timezone.utc) - timedelta(days=365)
    write_skill(
        user_skills,
        "untouchable",
        write_origin="curator",
        pinned=True,
        last_activity_at=long_ago,
    )

    changes = apply_transitions(
        stale_after_days=0,
        archive_after_days=0,
    )
    assert changes["marked_stale"] == []
    assert changes["archived"] == []

    fm, _ = parse_frontmatter(user_skills / "untouchable" / "SKILL.md")
    assert fm.state == "active"
    assert fm.pinned is True
