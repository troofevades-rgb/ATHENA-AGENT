"""Tests for the deterministic skill lifecycle state machine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ocode.skills.frontmatter import parse_frontmatter
from ocode.skills.state_machine import apply_transitions


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_active_to_stale_after_30_days(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "going-stale",
        write_origin="background_review",
        last_activity_at=_ago(31),
    )

    changes = apply_transitions()
    assert "going-stale" in changes["marked_stale"]
    fm, _ = parse_frontmatter(user_skills / "going-stale" / "SKILL.md")
    assert fm.state == "stale"


def test_stale_to_archived_after_90_days(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "ancient",
        state="stale",
        write_origin="curator",
        last_activity_at=_ago(91),
    )

    changes = apply_transitions()
    assert "ancient" in changes["archived"]
    assert not (user_skills / "ancient").exists()
    archived_path = user_skills / ".archive" / "ancient"
    assert archived_path.exists()
    fm, _ = parse_frontmatter(archived_path / "SKILL.md")
    assert fm.state == "archived"


def test_stale_reactivates_on_recent_activity(
    isolated_home: Path, write_skill
) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "reborn",
        state="stale",
        write_origin="background_review",
        last_activity_at=_ago(2),  # recent
    )

    changes = apply_transitions()
    assert "reborn" in changes["reactivated"]
    fm, _ = parse_frontmatter(user_skills / "reborn" / "SKILL.md")
    assert fm.state == "active"


def test_pinned_skips_all_transitions(isolated_home: Path, write_skill) -> None:
    """Covered by test_pin.py::test_pinned_skill_skips_state_transitions, but
    re-asserted here as part of the state machine's contract."""
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "pinned-ancient",
        pinned=True,
        write_origin="curator",
        last_activity_at=_ago(365),
    )

    changes = apply_transitions()
    assert "pinned-ancient" not in changes["archived"]
    assert "pinned-ancient" not in changes["marked_stale"]


def test_foreground_origin_skills_not_touched(
    isolated_home: Path, write_skill
) -> None:
    """Skills written by the user (foreground) are off-limits to the machine."""
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "user-owned",
        write_origin="foreground",
        last_activity_at=_ago(365),
    )

    changes = apply_transitions()
    assert "user-owned" not in changes["archived"]
    assert "user-owned" not in changes["marked_stale"]
    fm, _ = parse_frontmatter(user_skills / "user-owned" / "SKILL.md")
    assert fm.state == "active"


def test_migration_origin_skills_not_touched_until_local_activity(
    isolated_home: Path, write_skill
) -> None:
    """Migration-origin skills with no last_activity newer than imported_at
    are skipped — the curator should leave imports alone until the user
    actually starts using them."""
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "imported-untouched",
        write_origin="migration",
        imported_at=_ago(100),
        last_activity_at=_ago(100),  # equal to imported_at — no local activity
    )
    write_skill(
        user_skills,
        "imported-used",
        write_origin="migration",
        imported_at=_ago(100),
        last_activity_at=_ago(40),  # used after import
    )

    changes = apply_transitions()
    assert "imported-untouched" not in changes["marked_stale"]
    assert "imported-untouched" not in changes["archived"]
    assert "imported-used" in changes["marked_stale"]
