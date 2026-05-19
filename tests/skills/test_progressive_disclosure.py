"""Tests for athena.skills.progressive_disclosure.build_catalog."""

from __future__ import annotations

from pathlib import Path

from athena.skills.progressive_disclosure import build_catalog


def test_catalog_empty_when_no_skills(isolated_home: Path) -> None:
    assert build_catalog() == ""


def test_catalog_only_includes_active_and_stale(isolated_home: Path, write_skill) -> None:
    user = isolated_home / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "live")
    write_skill(user, "old", state="stale")

    archive = user / ".archive"
    archive.mkdir()
    write_skill(archive, "ancient", state="archived")

    catalog = build_catalog()
    assert "live" in catalog
    assert "old" in catalog
    assert "ancient" not in catalog


def test_catalog_one_line_per_skill(isolated_home: Path, write_skill) -> None:
    user = isolated_home / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "a", description="alpha")
    write_skill(user, "b", description="beta")
    write_skill(user, "c", description="gamma")

    catalog = build_catalog()
    skill_lines = [line for line in catalog.splitlines() if line.startswith("- ")]
    assert len(skill_lines) == 3


def test_catalog_truncated_at_max_length(isolated_home: Path, write_skill) -> None:
    user = isolated_home / ".athena" / "skills"
    user.mkdir(parents=True)
    for i in range(20):
        write_skill(user, f"sk-{i:02d}", description=f"description {i}")

    # Tight budget — only a few skill lines fit.
    catalog = build_catalog(max_chars=400)
    assert "more skills" in catalog
    assert len(catalog) <= 400


def test_pinned_skills_top_of_catalog(isolated_home: Path, write_skill) -> None:
    user = isolated_home / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "zzz-also", pinned=False)
    write_skill(user, "aaa-normal", pinned=False)
    write_skill(user, "mmm-pinned", pinned=True)

    catalog = build_catalog()
    pinned_idx = catalog.index("mmm-pinned")
    aaa_idx = catalog.index("aaa-normal")
    zzz_idx = catalog.index("zzz-also")
    assert pinned_idx < aaa_idx < zzz_idx


def test_catalog_marks_stale_explicitly(isolated_home: Path, write_skill) -> None:
    user = isolated_home / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "fresh")
    write_skill(user, "tired", state="stale")
    catalog = build_catalog()
    fresh_line = next(line for line in catalog.splitlines() if "fresh" in line)
    tired_line = next(line for line in catalog.splitlines() if "tired" in line)
    assert "(state: stale)" in tired_line
    assert "(state:" not in fresh_line


def test_catalog_active_pinned_then_active_then_stale(isolated_home: Path, write_skill) -> None:
    """Order is: pinned active first, then unpinned active, then stale."""
    user = isolated_home / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "stale-x", state="stale")
    write_skill(user, "active-y")
    write_skill(user, "active-z-pinned", pinned=True)

    catalog = build_catalog()
    lines = catalog.splitlines()
    skill_lines = [(i, ln) for i, ln in enumerate(lines) if ln.startswith("- ")]
    idx_pinned = next(i for i, ln in skill_lines if "active-z-pinned" in ln)
    idx_active = next(i for i, ln in skill_lines if "active-y" in ln)
    idx_stale = next(i for i, ln in skill_lines if "stale-x" in ln)
    assert idx_pinned < idx_active < idx_stale


def test_catalog_in_system_prompt(isolated_home: Path, write_skill) -> None:
    """The agent's build_system_prompt() must include the catalog when given."""
    from athena.prompts import build_system_prompt

    user = isolated_home / ".athena" / "skills"
    user.mkdir(parents=True)
    write_skill(user, "in-prompt", description="should appear in prompt")
    catalog = build_catalog()
    out = build_system_prompt(
        workspace=isolated_home,
        model="dummy",
        skills_catalog=catalog,
    )
    assert "in-prompt" in out
    assert "Skills available" in out
