"""Tests for athena.skills.validation.validate_skill."""

from __future__ import annotations

from pathlib import Path

from athena.skills.validation import validate_skill


def test_validate_clean_skill(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    skill_dir = write_skill(user_skills, "clean")
    assert validate_skill(skill_dir) == []


def test_validate_missing_skill_md(tmp_path: Path) -> None:
    d = tmp_path / "no-skill-md"
    d.mkdir()
    errors = validate_skill(d)
    assert any("missing SKILL.md" in e for e in errors)


def test_validate_malformed_frontmatter(tmp_path: Path) -> None:
    d = tmp_path / "bad"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: Has-Caps\ndescription: x\n---\n", encoding="utf-8")
    errors = validate_skill(d)
    assert any("lowercase" in e for e in errors)


def test_validate_invalid_state(tmp_path: Path) -> None:
    d = tmp_path / "weird-state"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: weird\ndescription: x\nstate: zombie\n---\n",
        encoding="utf-8",
    )
    errors = validate_skill(d)
    assert any("invalid state" in e for e in errors)


def test_validate_not_a_directory(tmp_path: Path) -> None:
    p = tmp_path / "file.txt"
    p.write_text("x", encoding="utf-8")
    errors = validate_skill(p)
    assert any("not a directory" in e for e in errors)
