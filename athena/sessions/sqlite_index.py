"""SQLite schema + FTS5 search helpers for the session store.

The SQLite database mirrors the JSONL files for fast keyword search. It is
authoritative for nothing — if you delete ``sessions.db``, ``athena reindex``
rebuilds it from the JSONL files in seconds.

The schema is small on purpose:

  * ``sessions`` — one row per session (metadata for filter joins).
  * ``turns``    — one row per appended message.
  * ``turns_fts``— FTS5 virtual table fed by triggers on ``turns``.

The two triggers (``turns_ai``, ``turns_ad``) keep the FTS5 index in sync
on insert and delete. FTS5's external-content mode means the body text
lives once in ``turns`` and the index references it by rowid.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    workspace TEXT,
    parent_session_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    tags TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_name TEXT,
    timestamp TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_index),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    content,
    content='turns',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
"""


def init_schema(db: sqlite3.Connection) -> None:
    """Idempotent — every CREATE has IF NOT EXISTS so it's safe to call repeatedly."""
    db.executescript(SCHEMA)
    db.commit()


def insert_session(db: sqlite3.Connection, meta: dict[str, Any]) -> None:
    """Insert a row into ``sessions``. ``meta`` should match the
    ``SessionMeta`` shape; ``tags`` is JSON-encoded.

    Uses ``INSERT OR REPLACE`` because reindex re-emits sessions whose row
    already exists from a prior partial run.
    """
    db.execute(
        "INSERT OR REPLACE INTO sessions "
        "(session_id, profile, model, provider, workspace, parent_session_id, "
        " started_at, ended_at, tags) "
        "VALUES (:session_id, :profile, :model, :provider, :workspace, "
        ":parent_session_id, :started_at, :ended_at, :tags)",
        {
            "session_id": meta["session_id"],
            "profile": meta["profile"],
            "model": meta["model"],
            "provider": meta["provider"],
            "workspace": meta.get("workspace"),
            "parent_session_id": meta.get("parent_session_id"),
            "started_at": _iso(meta.get("started_at")),
            "ended_at": _iso(meta.get("ended_at")),
            "tags": json.dumps(meta.get("tags") or []),
        },
    )
    db.commit()


def insert_turn(
    db: sqlite3.Connection,
    session_id: str,
    turn_index: int,
    role: str,
    content: str,
    tool_name: str | None,
    timestamp: str,
) -> None:
    db.execute(
        "INSERT OR REPLACE INTO turns "
        "(session_id, turn_index, role, content, tool_name, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, turn_index, role, content or "", tool_name, timestamp),
    )
    db.commit()


def update_session_ended(db: sqlite3.Connection, session_id: str, ended_at: datetime | str) -> None:
    db.execute(
        "UPDATE sessions SET ended_at = ? WHERE session_id = ?",
        (_iso(ended_at), session_id),
    )
    db.commit()


def fts5_search(
    db: sqlite3.Connection,
    query: str,
    *,
    k: int = 5,
    workspace: str | None = None,
    since: datetime | str | None = None,
) -> list[tuple[Any, ...]]:
    """Return ``(session_id, turn_index, role, content, tool_name,
    timestamp, started_at, workspace, score)`` rows ordered by BM25 rank.

    Wraps ``query`` for the FTS5 ``MATCH`` clause — callers pass the user-
    facing keyword string and we apply FTS5 quoting where needed.
    """
    bm25_alias = "bm25(turns_fts)"
    where: list[str] = ["turns_fts MATCH ?", "turns.rowid = turns_fts.rowid"]
    params: list[Any] = [query]

    if workspace is not None:
        where.append("sessions.workspace = ?")
        params.append(workspace)
    if since is not None:
        where.append("sessions.started_at >= ?")
        params.append(_iso(since))

    sql = (
        "SELECT turns.session_id, turns.turn_index, turns.role, turns.content, "
        "turns.tool_name, turns.timestamp, sessions.started_at, "
        f"sessions.workspace, {bm25_alias} AS score "
        "FROM turns_fts JOIN turns ON turns.rowid = turns_fts.rowid "
        "JOIN sessions ON sessions.session_id = turns.session_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY score ASC LIMIT ?"
    )
    params.append(k)
    return db.execute(sql, params).fetchall()


def reset(db: sqlite3.Connection) -> None:
    """Drop everything and recreate the schema. Used by ``reindex``."""
    db.executescript("""
        DROP TRIGGER IF EXISTS turns_ai;
        DROP TRIGGER IF EXISTS turns_ad;
        DROP TABLE IF EXISTS turns_fts;
        DROP TABLE IF EXISTS turns;
        DROP TABLE IF EXISTS sessions;
    """)
    db.commit()
    init_schema(db)


# -- internal helpers ----------------------------------------------------


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
