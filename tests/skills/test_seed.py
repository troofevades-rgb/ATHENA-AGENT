"""Tests for first-run default-skill seeding (athena/skills/seed.py)."""

from __future__ import annotations

from pathlib import Path

from athena.skills import seed


def test_default_skills_dir_exists_and_has_skills() -> None:
    src = seed.default_skills_dir()
    assert src.is_dir(), "athena/skills_default must ship with the package"
    names = [d.name for d in src.iterdir() if (d / "SKILL.md").exists()]
    assert len(names) >= 20, f"expected a real default-skill library, got {len(names)}"


def test_seeds_into_empty_dir(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    n = seed.seed_default_skills(root)
    assert n >= 20
    assert (root / ".defaults_seeded").exists()
    # A known skill landed with its SKILL.md.
    assert (root / "test-driven-development" / "SKILL.md").exists()


def test_idempotent_after_first_run(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    first = seed.seed_default_skills(root)
    second = seed.seed_default_skills(root)
    assert first >= 20
    assert second == 0  # sentinel short-circuits


def test_never_overwrites_existing_skill(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    mine = root / "test-driven-development"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("MY CUSTOM VERSION", encoding="utf-8")
    seed.seed_default_skills(root)
    # The user's edited copy is preserved, not clobbered by the default.
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "MY CUSTOM VERSION"


def test_force_reseeds_missing_only(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    seed.seed_default_skills(root)
    # Delete one, then force: it comes back, others untouched.
    import shutil

    shutil.rmtree(root / "spike")
    n = seed.seed_default_skills(root, force=True)
    assert n == 1
    assert (root / "spike" / "SKILL.md").exists()
