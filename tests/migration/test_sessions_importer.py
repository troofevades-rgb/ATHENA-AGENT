"""Tests for athena.migration.sessions_importer."""

from __future__ import annotations

import json
from pathlib import Path

from athena.migration.sessions_importer import import_sessions


def _write_session(hermes_source: Path, name: str, lines: list[dict]) -> Path:
    sessions = hermes_source / "sessions"
    sessions.mkdir(exist_ok=True)
    p = sessions / f"{name}.jsonl"
    p.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n",
        encoding="utf-8",
    )
    return p


def test_translates_jsonl_schema(hermes_source: Path, athena_dest: Path, migration_report) -> None:
    _write_session(
        hermes_source,
        "sess1",
        [
            {"_meta": {"model": "qwen2.5", "started_at": "2026-04-01T00:00:00Z"}},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
    )
    import_sessions(hermes_source, athena_dest, report=migration_report)

    out = athena_dest / "profiles" / "default" / "sessions" / "sess1.jsonl"
    assert out.exists()
    body_lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert body_lines == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_extracts_metadata_to_meta_json(
    hermes_source: Path, athena_dest: Path, migration_report
) -> None:
    _write_session(
        hermes_source,
        "with-meta",
        [
            {"_meta": {"model": "qwen2.5", "workspace": "/proj", "tags": ["x"]}},
            {"role": "user", "content": "go"},
        ],
    )
    import_sessions(hermes_source, athena_dest, report=migration_report)
    meta = json.loads(
        (athena_dest / "profiles" / "default" / "sessions" / "with-meta.meta.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["model"] == "qwen2.5"
    assert meta["workspace"] == "/proj"
    assert meta["tags"] == ["x"]
    assert meta["session_id"] == "with-meta"


def test_preserves_message_order(hermes_source: Path, athena_dest: Path, migration_report) -> None:
    msgs = [{"role": "user", "content": str(i)} for i in range(20)]
    _write_session(hermes_source, "ordered", msgs)
    import_sessions(hermes_source, athena_dest, report=migration_report)
    out = (athena_dest / "profiles" / "default" / "sessions" / "ordered.jsonl").read_text(
        encoding="utf-8"
    )
    parsed = [json.loads(line) for line in out.splitlines()]
    assert parsed == msgs


def test_fallback_meta_when_no_header(
    hermes_source: Path, athena_dest: Path, migration_report
) -> None:
    _write_session(
        hermes_source,
        "no-header",
        [
            {"role": "user", "content": "hello"},
        ],
    )
    import_sessions(hermes_source, athena_dest, report=migration_report)
    meta = json.loads(
        (athena_dest / "profiles" / "default" / "sessions" / "no-header.meta.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["session_id"] == "no-header"
    assert "started_at" in meta


def test_warns_when_no_sessions_dir(
    hermes_source: Path, athena_dest: Path, migration_report
) -> None:
    import_sessions(hermes_source, athena_dest, report=migration_report)
    warnings = migration_report.entries.get("sessions_warning", [])
    assert any(w.get("reason") == "no_sessions_dir" for w in warnings)
