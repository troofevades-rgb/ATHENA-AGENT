"""Tests for skill discovery."""

from __future__ import annotations

from pathlib import Path

from athena.skills.discovery import discover_skills, search_paths


def test_discover_user_skills(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "alpha", description="alpha")
    write_skill(user_skills, "beta", description="beta")

    found = discover_skills()
    assert set(found.keys()) == {"alpha", "beta"}


def test_discover_workspace_overrides_user(
    isolated_home: Path, workspace: Path, write_skill
) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    ws_skills = workspace / ".athena" / "skills"
    ws_skills.mkdir(parents=True)

    write_skill(user_skills, "shared", description="user version")
    write_skill(ws_skills, "shared", description="workspace version")
    write_skill(user_skills, "user-only", description="x")
    write_skill(ws_skills, "ws-only", description="x")

    found = discover_skills(workspace)
    assert set(found.keys()) == {"shared", "user-only", "ws-only"}
    fm, path = found["shared"]
    assert fm.description == "workspace version"
    assert path.parent == ws_skills


def test_discover_skips_archived_by_default(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    archive = user_skills / ".archive"
    archive.mkdir()

    write_skill(user_skills, "active-one")
    write_skill(archive, "old-one", state="archived")

    found = discover_skills()
    assert set(found.keys()) == {"active-one"}


def test_discover_include_archived(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    archive = user_skills / ".archive"
    archive.mkdir()
    write_skill(archive, "old-one", state="archived")
    write_skill(user_skills, "active-one")

    found = discover_skills(include_archived=True)
    assert set(found.keys()) == {"active-one", "old-one"}
    assert found["old-one"][0].state == "archived"


def test_discover_skips_malformed_skill_md(isolated_home: Path, write_skill, caplog) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "good")
    bad = user_skills / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: Has-Caps\ndescription: x\n---\n", encoding="utf-8")

    found = discover_skills()
    assert set(found.keys()) == {"good"}


def test_discover_empty_search_path(isolated_home: Path) -> None:
    assert discover_skills() == {}


def test_discover_ignores_loose_files(isolated_home: Path, write_skill) -> None:
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "real")
    (user_skills / "loose.txt").write_text("not a skill", encoding="utf-8")

    found = discover_skills()
    assert set(found.keys()) == {"real"}


def test_search_paths_filters_to_existing(isolated_home: Path, workspace: Path) -> None:
    # Neither dir exists yet.
    assert search_paths(workspace) == []
    # Create just the user dir.
    (isolated_home / ".athena" / "skills").mkdir(parents=True)
    assert search_paths(workspace) == [isolated_home / ".athena" / "skills"]
