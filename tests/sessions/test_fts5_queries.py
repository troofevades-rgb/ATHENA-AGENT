"""Tests for the FTS5 search semantics (matching, filters, ordering)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from athena.sessions import sqlite_index as idx


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
    idx.insert_session(
        con, _meta("s-foo", workspace="/foo", started_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    )
    idx.insert_session(
        con, _meta("s-bar", workspace="/bar", started_at=datetime(2026, 5, 1, tzinfo=timezone.utc))
    )
    idx.insert_turn(
        con, "s-foo", 0, "user", "the quick brown fox jumps", None, "2026-03-01T00:00:00Z"
    )
    idx.insert_turn(
        con, "s-foo", 1, "assistant", "elephants are also fast", None, "2026-03-01T00:00:01Z"
    )
    idx.insert_turn(
        con, "s-bar", 0, "user", "do quick foxes jump? running fast.", None, "2026-05-01T00:00:00Z"
    )
    idx.insert_turn(con, "s-bar", 1, "tool", "the tool result text", "Bash", "2026-05-01T00:00:01Z")
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
        db,
        "fox",
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


# ---- crash-safety: raw user input that isn't valid FTS5 syntax --------


@pytest.mark.parametrize(
    "query",
    [
        "don't",  # apostrophe
        "C:\\projects\\athena",  # backslashes + colon (column-filter char)
        "foo-bar",  # hyphen (NOT operator)
        'unbalanced "quote',  # unbalanced double quote
        "fox OR",  # trailing bare operator
        "(unclosed",  # unbalanced paren
        "NEAR",  # bare operator keyword
        "*",  # bare wildcard
        ": column",  # leading colon
    ],
)
def test_special_chars_dont_crash(db: sqlite3.Connection, query: str) -> None:
    """Regression: these raised sqlite3.OperationalError from MATCH,
    surfacing as a raw traceback from `athena sessions search`. They
    must now return a (possibly empty) result list, never raise."""
    hits = idx.fts5_search(db, query)
    assert isinstance(hits, list)


def test_apostrophe_term_still_matches_content(db: sqlite3.Connection) -> None:
    """`don't` should find content containing it once sanitized to a
    literal term (the apostrophe is a tokenizer separator → matches
    `don` `t`)."""
    idx.insert_turn(db, "s-foo", 2, "user", "please don't delete that", None, "2026-03-01T00:00:02Z")
    hits = idx.fts5_search(db, "don't")
    assert any(row[0] == "s-foo" for row in hits)


def test_empty_or_whitespace_query_returns_empty(db: sqlite3.Connection) -> None:
    assert idx.fts5_search(db, "") == []
    assert idx.fts5_search(db, "   ") == []


def test_valid_fts5_phrase_syntax_still_honored(db: sqlite3.Connection) -> None:
    """A valid quoted phrase is run as-is (true adjacency), not flattened
    to an AND of terms — power-user syntax is preserved when it parses."""
    # "brown fox" is adjacent in s-foo only.
    hits = idx.fts5_search(db, '"brown fox"')
    assert {row[0] for row in hits} == {"s-foo"}
