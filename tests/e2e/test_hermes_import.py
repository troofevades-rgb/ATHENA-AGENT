"""End-to-end migration tests against a programmatically-built Hermes home.

We build the fixture under tmp_path rather than checking in synthetic data;
the README in tests/fixtures/hermes_home_sample/ explains how to anonymize
real samples if a contributor wants to provide one later.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from athena.migration.hermes_import import run_import


@pytest.fixture
def hermes_home_sample(tmp_path: Path) -> Path:
    """Build a small but representative Hermes home and return its path."""
    src = tmp_path / "hermes-home"
    skills = src / "skills"
    skills.mkdir(parents=True)
    archive = skills / ".archive"
    archive.mkdir()
    sessions = src / "sessions"
    sessions.mkdir()

    # Two active skills (one with references)
    (skills / "example-skill-a").mkdir()
    (skills / "example-skill-a" / "SKILL.md").write_text(
        "---\nname: example-skill-a\ndescription: First example.\nversion: '1.0'\n---\nbody A\n",
        encoding="utf-8",
    )
    (skills / "example-skill-a" / "references").mkdir()
    (skills / "example-skill-a" / "references" / "notes.md").write_text(
        "ref content\n", encoding="utf-8"
    )

    (skills / "example-skill-b").mkdir()
    (skills / "example-skill-b" / "SKILL.md").write_text(
        "---\nname: example-skill-b\ndescription: Second example.\n---\nbody B\n",
        encoding="utf-8",
    )

    # One archived skill
    (archive / "old-skill").mkdir()
    (archive / "old-skill" / "SKILL.md").write_text(
        "---\nname: old-skill\ndescription: Retired.\n---\nold body\n",
        encoding="utf-8",
    )

    # config.yaml
    (src / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": "qwen2.5-coder:14b",
                "ollama_host": "http://localhost:11434",
                "context_window": 32768,
                "openai_api_key": "sk-fake",
                "custom_thing": "preserve me",
            }
        ),
        encoding="utf-8",
    )

    # mcp.json
    (src / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fs": {"command": "uvx", "args": ["mcp-fs"]},
                    "remote": {"transport": "http", "url": "http://x"},
                }
            }
        ),
        encoding="utf-8",
    )

    # sessions
    (sessions / "session-001.jsonl").write_text(
        json.dumps({"_meta": {"model": "qwen2.5"}})
        + "\n"
        + json.dumps({"role": "user", "content": "hi"})
        + "\n",
        encoding="utf-8",
    )
    (sessions / "session-002.jsonl").write_text(
        json.dumps({"role": "user", "content": "no header"}) + "\n",
        encoding="utf-8",
    )

    # memory.db with a couple rows
    db = src / "memory.db"
    con = sqlite3.connect(str(db))
    con.execute("""
        CREATE TABLE memory_entries (
            id INTEGER PRIMARY KEY, profile TEXT, name TEXT, type TEXT,
            description TEXT, body TEXT, write_origin TEXT,
            created_at TEXT, last_used_at TEXT
        )
    """)
    con.executemany(
        "INSERT INTO memory_entries (profile, name, type, description, body, write_origin) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("default", "user role", "user", "ds", "ds body", "foreground"),
            ("default", "merge freeze", "project", "freeze", "freeze body", "foreground"),
        ],
    )
    con.commit()
    con.close()

    return src


def test_full_import_against_fixture_hermes_home(hermes_home_sample: Path, tmp_path: Path) -> None:
    dest = tmp_path / "athena-out"
    report_dir = run_import(hermes_home_sample, dest)

    # Skills are imported
    assert (dest / "skills" / "example-skill-a" / "SKILL.md").exists()
    assert (dest / "skills" / "example-skill-a" / "references" / "notes.md").exists()
    assert (dest / "skills" / "example-skill-b" / "SKILL.md").exists()
    assert (dest / "skills" / ".archive" / "old-skill" / "SKILL.md").exists()
    # Memory is imported
    assert (dest / "profiles" / "default" / "memory" / "user_role.md").exists()
    assert (dest / "profiles" / "default" / "memory" / "MEMORY.md").exists()
    # Sessions are imported with meta sidecars
    assert (dest / "profiles" / "default" / "sessions" / "session-001.jsonl").exists()
    assert (dest / "profiles" / "default" / "sessions" / "session-001.meta.json").exists()
    # Config + credentials
    assert (dest / "config.toml").exists()
    assert (dest / "credentials.json").exists()
    # mcp.json
    assert (dest / "mcp.json").exists()
    # Report
    assert (report_dir / "REPORT.md").exists()
    assert (report_dir / "summary.json").exists()


def test_dry_run_makes_no_changes(hermes_home_sample: Path, tmp_path: Path) -> None:
    dest = tmp_path / "athena-out"
    run_import(hermes_home_sample, dest, dry_run=True)
    # Only the report directory should exist; no skills/memory/etc.
    assert not (dest / "skills").exists()
    assert not (dest / "profiles").exists()
    assert not (dest / "config.toml").exists()
    assert not (dest / "mcp.json").exists()
    # But the report is still written.
    logs = list((dest / "logs" / "migration").iterdir())
    assert len(logs) == 1
    assert (logs[0] / "REPORT.md").exists()


def test_report_lists_all_imported_artifacts(hermes_home_sample: Path, tmp_path: Path) -> None:
    dest = tmp_path / "athena-out"
    report_dir = run_import(hermes_home_sample, dest)
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    counts = summary["counts"]
    assert counts.get("imported_skill", 0) >= 3  # a, b, old-skill
    assert counts.get("imported_memory", 0) == 2
    assert counts.get("imported_session", 0) == 2
    assert counts.get("imported_config", 0) == 1
    assert counts.get("imported_mcp", 0) == 1
    # http transport got disabled with a warning
    assert any(
        w.get("server") == "remote" and "http" in w.get("transport", "")
        for w in summary["entries"].get("mcp_warning", [])
    )


def test_post_import_validation_passes(hermes_home_sample: Path, tmp_path: Path) -> None:
    """Every imported skill must parse via the athena v2 validator."""
    from athena.skills.validation import validate_skill

    dest = tmp_path / "athena-out"
    run_import(hermes_home_sample, dest)
    for skill_dir in (dest / "skills").iterdir():
        if skill_dir.is_dir() and not skill_dir.name.startswith("."):
            assert validate_skill(skill_dir) == []
    for skill_dir in (dest / "skills" / ".archive").iterdir():
        if skill_dir.is_dir():
            assert validate_skill(skill_dir) == []


def test_second_run_is_idempotent(hermes_home_sample: Path, tmp_path: Path) -> None:
    dest = tmp_path / "athena-out"
    run_import(hermes_home_sample, dest)
    report_dir = run_import(hermes_home_sample, dest)
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    # The second run should skip every prior-migration skill.
    assert summary["counts"].get("skipped_prior_migration", 0) >= 3
    assert summary["counts"].get("conflict_renamed", 0) == 0


def test_cli_entry_point_dispatches(
    monkeypatch, hermes_home_sample: Path, tmp_path: Path, capsys
) -> None:
    """athena import-from-hermes --source X --dest Y --no-confirm dispatches
    through __main__.main() and returns 0."""
    from athena import __main__ as main_mod

    dest = tmp_path / "athena-out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "athena",
            "import-from-hermes",
            "--source",
            str(hermes_home_sample),
            "--dest",
            str(dest),
            "--no-confirm",
        ],
    )
    rc = main_mod.main()
    assert rc == 0
    assert (dest / "skills" / "example-skill-a").exists()
