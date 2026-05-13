"""Tests for ocode.sessions.reindex.reindex()."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ocode.sessions.reindex import reindex
from ocode.sessions.store import SessionMeta, SessionStore, new_session_id


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    d = tmp_path / "profiles" / "default"
    d.mkdir(parents=True)
    return d


def _seed_session(profile_dir: Path, session_id: str, messages: list[dict]) -> None:
    store = SessionStore(profile_dir)
    try:
        meta = SessionMeta(
            session_id=session_id,
            profile="default",
            model="qwen2.5",
            provider="ollama",
            workspace="/proj",
        )
        store.open_session(meta)
        for m in messages:
            store.append_turn(session_id, m)
    finally:
        store.close()


def test_rebuild_from_empty_db(profile_dir: Path) -> None:
    sid = new_session_id()
    _seed_session(profile_dir, sid, [
        {"role": "user", "content": "alpha bravo charlie"},
        {"role": "assistant", "content": "delta echo"},
    ])
    db_path = profile_dir / "sessions.db"
    assert db_path.exists()
    db_path.unlink()

    summary = reindex(profile_dir)
    assert summary["sessions"] == 1
    assert summary["turns"] == 2

    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT session_id, turn_index FROM turns ORDER BY turn_index"
        ).fetchall()
        assert rows == [(sid, 0), (sid, 1)]
        # FTS5 round-trips after the rebuild.
        match = con.execute(
            "SELECT rowid FROM turns_fts WHERE turns_fts MATCH 'bravo'"
        ).fetchall()
        assert len(match) == 1
    finally:
        con.close()


def test_rebuild_preserves_meta_fields(profile_dir: Path) -> None:
    sid = new_session_id()
    _seed_session(profile_dir, sid, [{"role": "user", "content": "x"}])
    # Delete DB; meta.json is the only metadata source.
    (profile_dir / "sessions.db").unlink()

    reindex(profile_dir)
    con = sqlite3.connect(str(profile_dir / "sessions.db"))
    try:
        row = con.execute(
            "SELECT workspace, model, provider FROM sessions WHERE session_id=?",
            (sid,),
        ).fetchone()
        assert row == ("/proj", "qwen2.5", "ollama")
    finally:
        con.close()


def test_rebuild_after_jsonl_corruption_skips_bad_lines(profile_dir: Path) -> None:
    sid = new_session_id()
    _seed_session(profile_dir, sid, [
        {"role": "user", "content": "good first"},
        {"role": "user", "content": "good second"},
    ])
    # Corrupt the middle line.
    jsonl_path = profile_dir / "sessions" / f"{sid}.jsonl"
    text = jsonl_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    lines.insert(1, "{not json")
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    (profile_dir / "sessions.db").unlink()
    summary = reindex(profile_dir)
    # Two valid turns survive, the broken line is silently skipped.
    assert summary["sessions"] == 1
    assert summary["turns"] == 2


def test_rebuild_is_idempotent(profile_dir: Path) -> None:
    _seed_session(profile_dir, new_session_id(), [{"role": "user", "content": "first"}])
    first = reindex(profile_dir)
    second = reindex(profile_dir)
    assert first["sessions"] == second["sessions"]
    assert first["turns"] == second["turns"]


def test_reindex_no_sessions_dir(tmp_path: Path) -> None:
    summary = reindex(tmp_path / "no-profile")
    assert summary == {"sessions": 0, "turns": 0, "skipped_files": [], "duration_s": 0.0}


def test_reindex_constructs_meta_when_sidecar_missing(profile_dir: Path) -> None:
    """A bare JSONL file (no .meta.json) should still reindex with a fallback meta row."""
    sid = "barefile"
    sessions_dir = profile_dir / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / f"{sid}.jsonl").write_text(
        json.dumps({"role": "user", "content": "lonely turn"}) + "\n",
        encoding="utf-8",
    )
    summary = reindex(profile_dir)
    assert summary["sessions"] == 1
    assert summary["turns"] == 1
    con = sqlite3.connect(str(profile_dir / "sessions.db"))
    try:
        row = con.execute(
            "SELECT session_id, model FROM sessions WHERE session_id=?", (sid,)
        ).fetchone()
        assert row == (sid, "unknown")
    finally:
        con.close()
