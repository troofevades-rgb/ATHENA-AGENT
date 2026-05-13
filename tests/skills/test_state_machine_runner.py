"""Tests for the lifecycle runner that wires apply_transitions into Agent init."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ocode.skills.frontmatter import parse_frontmatter
from ocode.skills.state_machine_runner import run_lifecycle


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_runs_at_session_init(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "going-stale",
        write_origin="background_review",
        last_activity_at=_ago(45),
    )
    actions = run_lifecycle()
    assert "going-stale" in actions["marked_stale"]
    fm, _ = parse_frontmatter(user_skills / "going-stale" / "SKILL.md")
    assert fm.state == "stale"


def test_writes_frontmatter_changes_atomically(isolated_home: Path, write_skill) -> None:
    """An apply pass that fails partway should still leave each individual
    skill's frontmatter in a valid state — the unit of atomicity is per-skill."""
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "a", write_origin="curator", last_activity_at=_ago(100))
    write_skill(user_skills, "b", write_origin="curator", last_activity_at=_ago(5))
    run_lifecycle()
    # a is archived (>90 days), b is untouched (<30 days).
    assert (user_skills / ".archive" / "a").exists()
    fm_b, _ = parse_frontmatter(user_skills / "b" / "SKILL.md")
    assert fm_b.state == "active"


def test_logs_action_counts(
    isolated_home: Path, write_skill, caplog
) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "loud",
        write_origin="background_review",
        last_activity_at=_ago(45),
    )
    import logging
    with caplog.at_level(logging.INFO, logger="ocode.skills.state_machine_runner"):
        run_lifecycle()
    assert any("lifecycle" in rec.message for rec in caplog.records)


def test_no_action_returns_empty_lists(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(
        user_skills,
        "fresh",
        write_origin="background_review",
        last_activity_at=_ago(1),
    )
    actions = run_lifecycle()
    assert actions["marked_stale"] == []
    assert actions["archived"] == []
    assert actions["reactivated"] == []


def test_failure_is_swallowed(monkeypatch, isolated_home: Path) -> None:
    """If apply_transitions raises, run_lifecycle returns empty lists rather
    than letting the exception bubble into Agent init."""
    import ocode.skills.state_machine_runner as runner_mod

    def boom(*a, **k):
        raise RuntimeError("simulated")

    monkeypatch.setattr(runner_mod.state_machine, "apply_transitions", boom)
    result = runner_mod.run_lifecycle()
    assert result == {"marked_stale": [], "archived": [], "reactivated": []}
