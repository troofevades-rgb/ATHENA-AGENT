"""Tests for athena.migration.skills_mapper.import_skills."""

from __future__ import annotations

from pathlib import Path

from athena.migration.skills_mapper import import_skills
from athena.skills.frontmatter import parse_frontmatter


def test_imports_hermes_skill_with_full_frontmatter(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    hermes_skill_factory(
        hermes_source,
        "full",
        description="Full skill.",
        extra={
            "version": "1.2.3",
            "license": "MIT",
            "author": "alice",
            "platforms": ["linux", "macos"],
            "metadata": {"category": "tools"},
            "created_at": "2024-06-01T00:00:00Z",
            "last_activity_at": "2025-12-01T00:00:00Z",
        },
    )

    import_skills(hermes_source, ocode_dest, report=migration_report)

    imported_dir = ocode_dest / "skills" / "full"
    assert imported_dir.exists()
    fm, body = parse_frontmatter(imported_dir / "SKILL.md")
    assert fm.name == "full"
    assert fm.description == "Full skill."
    assert fm.version == "1.2.3"
    assert fm.license == "MIT"
    assert fm.write_origin == "migration"
    assert fm.state == "active"
    assert fm.source_hermes_path.endswith("full")
    assert fm.imported_at is not None
    # Hermes-only fields land in metadata.
    assert fm.metadata.get("author") == "alice"
    assert fm.metadata.get("platforms") == ["linux", "macos"]
    assert fm.metadata.get("category") == "tools"
    assert "Hermes skill body" in body


def test_imports_hermes_skill_minimal_frontmatter_with_defaults(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    hermes_skill_factory(hermes_source, "bare", description="Bare.")
    import_skills(hermes_source, ocode_dest, report=migration_report)

    fm, _ = parse_frontmatter(ocode_dest / "skills" / "bare" / "SKILL.md")
    assert fm.write_origin == "migration"
    assert fm.created_at is not None  # fell back to mtime
    assert fm.last_activity_at is not None


def test_imports_with_references_subdir(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    skill_dir = hermes_skill_factory(hermes_source, "refsk")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "notes.md").write_text("ref content\n", encoding="utf-8")

    import_skills(hermes_source, ocode_dest, report=migration_report)
    assert (ocode_dest / "skills" / "refsk" / "references" / "notes.md").read_text(
        encoding="utf-8"
    ) == "ref content\n"


def test_imports_with_templates_subdir(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    skill_dir = hermes_skill_factory(hermes_source, "tmpsk")
    tmpls = skill_dir / "templates"
    tmpls.mkdir()
    (tmpls / "scaffold.py").write_text("# template\n", encoding="utf-8")

    import_skills(hermes_source, ocode_dest, report=migration_report)
    assert (ocode_dest / "skills" / "tmpsk" / "templates" / "scaffold.py").exists()


def test_imports_with_scripts_subdir(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    skill_dir = hermes_skill_factory(hermes_source, "scsk")
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "go.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")

    import_skills(hermes_source, ocode_dest, report=migration_report)
    assert (ocode_dest / "skills" / "scsk" / "scripts" / "go.sh").exists()


def test_imports_archived_skill(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    hermes_skill_factory(hermes_source, "old-skill", archived=True)
    import_skills(hermes_source, ocode_dest, report=migration_report)

    archived_dest = ocode_dest / "skills" / ".archive" / "old-skill"
    assert archived_dest.exists()
    fm, _ = parse_frontmatter(archived_dest / "SKILL.md")
    assert fm.state == "archived"
    assert fm.write_origin == "migration"


def test_import_conflict_renames_with_from_hermes_suffix(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    # Pre-existing destination skill that is NOT a prior migration.
    existing = ocode_dest / "skills" / "collide"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text(
        "---\nname: collide\ndescription: existing\nwrite_origin: foreground\n---\nlocal\n",
        encoding="utf-8",
    )

    hermes_skill_factory(hermes_source, "collide", description="incoming")
    import_skills(hermes_source, ocode_dest, report=migration_report)

    renamed = ocode_dest / "skills" / "collide-from-hermes"
    assert renamed.exists()
    fm, _ = parse_frontmatter(renamed / "SKILL.md")
    # The frontmatter name was rewritten so discovery still works.
    assert fm.name == "collide-from-hermes"
    assert migration_report.count("conflict_renamed") == 1
    # Original local skill is untouched.
    local_fm, _ = parse_frontmatter(existing / "SKILL.md")
    assert local_fm.write_origin == "foreground"


def test_import_skips_prior_migration_with_warning(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    # Run an import, then re-run; the second run must skip.
    hermes_skill_factory(hermes_source, "twice")
    import_skills(hermes_source, ocode_dest, report=migration_report)
    assert migration_report.count("imported_skill") == 1
    import_skills(hermes_source, ocode_dest, report=migration_report)
    assert migration_report.count("skipped_prior_migration") == 1


def test_imported_skill_has_migration_origin(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    hermes_skill_factory(hermes_source, "origin-test")
    import_skills(hermes_source, ocode_dest, report=migration_report)
    fm, _ = parse_frontmatter(ocode_dest / "skills" / "origin-test" / "SKILL.md")
    assert fm.write_origin == "migration"
    assert fm.imported_at is not None
    assert fm.source_hermes_path.endswith("origin-test")


def test_dry_run_skips_writes(
    hermes_source: Path, ocode_dest: Path, migration_report, hermes_skill_factory
) -> None:
    hermes_skill_factory(hermes_source, "dryskill")
    import_skills(hermes_source, ocode_dest, report=migration_report, dry_run=True)
    assert not (ocode_dest / "skills" / "dryskill").exists()
    assert migration_report.count("imported_skill") == 1


def test_malformed_hermes_skill_is_skipped(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    bad_dir = hermes_source / "skills" / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    import_skills(hermes_source, ocode_dest, report=migration_report)
    assert migration_report.count("skipped_malformed") == 1
    assert not (ocode_dest / "skills" / "bad").exists()
