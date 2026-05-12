"""Tests for the on-demand skill body loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from ocode.skills import loader


def test_load_full_body(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "alpha", body="# alpha\n\nHere is the body.\n")
    body = loader.load_body("alpha")
    assert body is not None
    assert "Here is the body." in body


def test_load_returns_none_when_missing(isolated_home: Path) -> None:
    assert loader.load_body("nope") is None


def test_load_with_references_subdir(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    skill_dir = write_skill(user_skills, "withrefs")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "notes.md").write_text("# notes\n\ndetails here\n", encoding="utf-8")

    content = loader.load_reference("withrefs", "references/notes.md")
    assert content is not None
    assert "details here" in content


def test_load_caches_body(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    skill_dir = write_skill(user_skills, "cached", body="original\n")

    first = loader.load_body("cached")
    # Mutate the file directly; the cache should still return the first read.
    skill_md = skill_dir / "SKILL.md"
    new_text = skill_md.read_text(encoding="utf-8").replace("original", "REWRITTEN")
    skill_md.write_text(new_text, encoding="utf-8")
    cached = loader.load_body("cached")
    assert cached == first
    assert "original" in cached

    # After invalidate, the next read sees the new content.
    loader.invalidate("cached")
    fresh = loader.load_body("cached")
    assert "REWRITTEN" in fresh


def test_load_reference_rejects_traversal(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "trav")
    with pytest.raises(ValueError, match="'..'"):
        loader.load_reference("trav", "references/../../etc/passwd")


def test_load_reference_rejects_absolute(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "abs")
    with pytest.raises(ValueError, match="must be relative"):
        loader.load_reference("abs", "/etc/passwd")


def test_load_reference_rejects_unknown_subdir(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "sub")
    with pytest.raises(ValueError, match="must start with"):
        loader.load_reference("sub", "secret/data.txt")


def test_load_reference_missing_file(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".ocode" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "missing-ref")
    assert loader.load_reference("missing-ref", "references/nope.md") is None
