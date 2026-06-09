"""Tests for athena.migration.memory_exporter."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from athena.migration.memory_exporter import export_memory


def _build_hermes_db(db_path: Path, rows: list[dict]) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("""
            CREATE TABLE memory_entries (
                id INTEGER PRIMARY KEY,
                profile TEXT,
                name TEXT,
                type TEXT,
                description TEXT,
                body TEXT,
                write_origin TEXT,
                created_at TEXT,
                last_used_at TEXT
            )
        """)
        for r in rows:
            con.execute(
                """
                INSERT INTO memory_entries
                (profile, name, type, description, body, write_origin, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    r.get("profile", "default"),
                    r["name"],
                    r.get("type", "user"),
                    r.get("description", ""),
                    r.get("body", ""),
                    r.get("write_origin", "foreground"),
                    r.get("created_at"),
                    r.get("last_used_at"),
                ),
            )
        con.commit()
    finally:
        con.close()


def test_exports_sqlite_to_markdown_files(
    hermes_source: Path, athena_dest: Path, migration_report
) -> None:
    _build_hermes_db(
        hermes_source / "memory.db",
        [
            {
                "name": "user role",
                "type": "user",
                "description": "data scientist",
                "body": "interested in observability",
            },
            {"name": "merge freeze", "type": "project", "body": "merge freeze starts 2026-03-05"},
        ],
    )
    export_memory(hermes_source, athena_dest, report=migration_report)

    mem_dir = athena_dest / "profiles" / "default" / "memory"
    files = sorted(p.name for p in mem_dir.glob("*.md"))
    assert "user_role.md" in files
    assert "merge_freeze.md" in files
    user_md = (mem_dir / "user_role.md").read_text(encoding="utf-8")
    # Frontmatter values are quoted to defend against YAML injection
    # from untrusted SQLite sources; verify by YAML-parsing the front
    # matter rather than literal-string-matching the (quoted) values.
    import yaml as _yaml

    _, fm_text, _ = user_md.split("---", 2)
    fm = _yaml.safe_load(fm_text)
    assert fm["name"] == "user role"
    assert fm["write_origin"] == "migration"
    assert fm["description"] == "data scientist"


def test_rebuilds_memory_md_index(hermes_source: Path, athena_dest: Path, migration_report) -> None:
    _build_hermes_db(
        hermes_source / "memory.db",
        [
            {"name": "alpha", "body": "x"},
            {"name": "beta", "body": "y"},
        ],
    )
    export_memory(hermes_source, athena_dest, report=migration_report)
    index = (athena_dest / "profiles" / "default" / "memory" / "MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert "alpha" in index
    assert "beta" in index


def test_preserves_created_at_and_last_used_at(
    hermes_source: Path, athena_dest: Path, migration_report
) -> None:
    created = datetime(2024, 6, 1, tzinfo=timezone.utc).isoformat()
    last = datetime(2026, 2, 14, tzinfo=timezone.utc).isoformat()
    _build_hermes_db(
        hermes_source / "memory.db",
        [
            {"name": "preserved", "body": "x", "created_at": created, "last_used_at": last},
        ],
    )
    export_memory(hermes_source, athena_dest, report=migration_report)
    text = (athena_dest / "profiles" / "default" / "memory" / "preserved.md").read_text(
        encoding="utf-8"
    )
    assert created in text
    assert last in text


def test_warns_on_unknown_memory_provider(
    hermes_source: Path, athena_dest: Path, migration_report
) -> None:
    (hermes_source / "memory_provider").write_text("byterover\n", encoding="utf-8")
    export_memory(hermes_source, athena_dest, report=migration_report)
    warnings = migration_report.entries.get("memory_warning", [])
    assert any("byterover" in w.get("provider", "") for w in warnings)
    assert migration_report.count("imported_memory") == 0


def test_warns_when_no_memory_db(hermes_source: Path, athena_dest: Path, migration_report) -> None:
    export_memory(hermes_source, athena_dest, report=migration_report)
    warnings = migration_report.entries.get("memory_warning", [])
    assert any(w.get("reason") == "no_db" for w in warnings)
