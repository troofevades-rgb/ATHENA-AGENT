"""Tests for the schema, triggers, and structural helpers of the SQLite index."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from athena.sessions import sqlite_index as idx


@pytest.fixture
def db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    idx.init_schema(con)
    return con


def _meta(session_id: str = "s1", **over) -> dict:
    base = {
        "session_id": session_id,
        "profile": "default",
        "model": "qwen2.5",
        "provider": "ollama",
        "workspace": "/proj",
        "parent_session_id": None,
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "ended_at": None,
        "tags": [],
    }
    base.update(over)
    return base


def test_schema_created_on_first_open(db: sqlite3.Connection) -> None:
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger') ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    for required in (
        "sessions",
        "turns",
        "turns_fts",
        "turns_ai",
        "turns_ad",
        "idx_sessions_started",
        "idx_sessions_workspace",
    ):
        assert required in names, f"missing schema object: {required}"


def test_init_schema_is_idempotent(db: sqlite3.Connection) -> None:
    idx.init_schema(db)
    idx.init_schema(db)  # second call must not raise


def test_fts_trigger_indexes_on_insert(db: sqlite3.Connection) -> None:
    idx.insert_session(db, _meta())
    idx.insert_turn(db, "s1", 0, "user", "the quick brown fox", None, "2026-01-01T00:00:00Z")
    matches = db.execute("SELECT rowid FROM turns_fts WHERE turns_fts MATCH 'quick'").fetchall()
    assert len(matches) == 1


def test_fts_trigger_removes_on_delete(db: sqlite3.Connection) -> None:
    idx.insert_session(db, _meta())
    idx.insert_turn(db, "s1", 0, "user", "hello world", None, "2026-01-01T00:00:00Z")
    db.execute("DELETE FROM turns WHERE session_id = 's1' AND turn_index = 0")
    db.commit()
    matches = db.execute("SELECT rowid FROM turns_fts WHERE turns_fts MATCH 'hello'").fetchall()
    assert matches == []


def test_indexes_exist(db: sqlite3.Connection) -> None:
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='sessions'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_sessions_started" in names
    assert "idx_sessions_workspace" in names


def test_update_session_ended(db: sqlite3.Connection) -> None:
    idx.insert_session(db, _meta())
    idx.update_session_ended(db, "s1", "2026-01-02T00:00:00Z")
    row = db.execute("SELECT ended_at FROM sessions WHERE session_id='s1'").fetchone()
    assert row[0] == "2026-01-02T00:00:00Z"


def test_reset_clears_state(db: sqlite3.Connection) -> None:
    idx.insert_session(db, _meta())
    idx.insert_turn(db, "s1", 0, "user", "hi", None, "2026-01-01T00:00:00Z")
    idx.reset(db)
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
    # Schema still works after reset.
    idx.insert_session(db, _meta("after-reset"))
    idx.insert_turn(db, "after-reset", 0, "user", "hello", None, "2026-01-01T00:00:00Z")
    matches = idx.fts5_search(db, "hello")
    assert {row[0] for row in matches} == {"after-reset"}
