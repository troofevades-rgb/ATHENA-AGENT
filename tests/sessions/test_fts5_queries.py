"""Tests for the FTS5 search semantics (matching, filters, ordering)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from ocode.sessions import sqlite_index as idx


def _meta(session_id: str, **over) -> dict:
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


@pytest.fixture
def db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    idx.init_schema(con)
    idx.insert_session(con, _meta("s-foo", workspace="/foo",
                                  started_at=datetime(2026, 3, 1, tzinfo=timezone.utc)))
    idx.insert_session(con, _meta("s-bar", workspace="/bar",
                                  started_at=datetime(2026, 5, 1, tzinfo=timezone.utc)))
    idx.insert_turn(con, "s-foo", 0, "user", "the quick brown fox jumps",
                    None, "2026-03-01T00:00:00Z")
    idx.insert_turn(con, "s-foo", 1, "assistant", "elephants are also fast",
                    None, "2026-03-01T00:00:01Z")
    idx.insert_turn(con, "s-bar", 0, "user", "do quick foxes jump? running fast.",
                    None, "2026-05-01T00:00:00Z")
    idx.insert_turn(con, "s-bar", 1, "tool", "the tool result text", "Bash",
                    "2026-05-01T00:00:01Z")
    return con


def test_basic_word_match(db: sqlite3.Connection) -> None:
    hits = idx.fts5_search(db, "fox")
    sessions = {row[0] for row in hits}
    assert sessions == {"s-foo", "s-bar"}


def test_phrase_match_quoted(db: sqlite3.Connection) -> None:
    hits = idx.fts5_search(db, '"brown fox"')
    assert {row[0] for row in hits} == {"s-foo"}


def test_porter_stem_matches_root(db: sqlite3.Connection) -> None:
    hits = idx.fts5_search(db, "jump")
    assert {row[0] for row in hits} == {"s-foo", "s-bar"}


def test_filter_by_workspace(db: sqlite3.Connection) -> None:
    hits = idx.fts5_search(db, "fox", workspace="/foo")
    assert {row[0] for row in hits} == {"s-foo"}


def test_filter_by_since(db: sqlite3.Connection) -> None:
    hits = idx.fts5_search(
        db, "fox",
        since=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    assert {row[0] for row in hits} == {"s-bar"}


def test_top_k_ordering(db: sqlite3.Connection) -> None:
    one = idx.fts5_search(db, "fox jump", k=1)
    assert len(one) == 1
    several = idx.fts5_search(db, "fox jump", k=10)
    # BM25 returns lower scores for better matches; the first row should
    # have score <= all subsequent rows.
    scores = [row[-1] for row in several]
    assert scores == sorted(scores)
