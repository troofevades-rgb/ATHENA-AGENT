"""Tests for athena.sessions.store.SessionStore."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from athena.sessions.store import (
    SessionMeta,
    SessionStore,
    new_session_id,
)


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    d = tmp_path / "profiles" / "default"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def store(profile_dir: Path) -> SessionStore:
    s = SessionStore(profile_dir)
    yield s
    s.close()


def _meta(session_id: str | None = None, **over) -> SessionMeta:
    return SessionMeta(
        session_id=session_id or new_session_id(),
        profile="default",
        model="qwen2.5",
        provider="ollama",
        workspace=over.pop("workspace", "/proj"),
        **over,
    )


def test_open_session_writes_meta_json(store: SessionStore, profile_dir: Path) -> None:
    meta = _meta()
    store.open_session(meta)
    meta_path = profile_dir / "sessions" / f"{meta.session_id}.meta.json"
    assert meta_path.exists()
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["session_id"] == meta.session_id
    assert data["model"] == "qwen2.5"


def test_append_turn_persists_to_jsonl(store: SessionStore, profile_dir: Path) -> None:
    meta = _meta()
    store.open_session(meta)
    idx1 = store.append_turn(meta.session_id, {"role": "user", "content": "hi"})
    idx2 = store.append_turn(meta.session_id, {"role": "assistant", "content": "hello"})
    assert idx1 == 0
    assert idx2 == 1

    jsonl_path = profile_dir / "sessions" / f"{meta.session_id}.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"role": "user", "content": "hi"}


def test_append_turn_indexes_to_fts5(store: SessionStore) -> None:
    meta = _meta()
    store.open_session(meta)
    store.append_turn(meta.session_id, {"role": "user", "content": "the quick brown fox"})
    hits = store.search("fox")
    assert len(hits) == 1
    assert hits[0].session_id == meta.session_id
    assert hits[0].turn_index == 0
    assert "fox" in hits[0].snippet


def test_close_session_writes_ended_at(store: SessionStore, profile_dir: Path) -> None:
    meta = _meta()
    store.open_session(meta)
    store.close_session(meta.session_id)
    data = json.loads(
        (profile_dir / "sessions" / f"{meta.session_id}.meta.json").read_text(encoding="utf-8")
    )
    assert data["ended_at"] is not None


def test_load_streams_messages_in_order(store: SessionStore) -> None:
    meta = _meta()
    store.open_session(meta)
    for i in range(5):
        store.append_turn(meta.session_id, {"role": "user", "content": f"msg-{i}"})
    loaded = list(store.load(meta.session_id))
    assert [m["content"] for m in loaded] == [f"msg-{i}" for i in range(5)]


def test_list_sessions_orders_by_started_at_desc(store: SessionStore) -> None:
    now = datetime.now(timezone.utc)
    older = _meta("older", started_at=now - timedelta(hours=2))
    newer = _meta("newer", started_at=now - timedelta(minutes=10))
    store.open_session(older)
    store.open_session(newer)
    listed = store.list_sessions()
    assert [m.session_id for m in listed[:2]] == ["newer", "older"]


def test_list_sessions_respects_limit_and_before(store: SessionStore) -> None:
    now = datetime.now(timezone.utc)
    for i in range(5):
        store.open_session(_meta(f"s{i}", started_at=now - timedelta(hours=i)))
    listed = store.list_sessions(limit=2)
    assert len(listed) == 2
    # before-filter: cuts everything started >= cursor
    older = store.list_sessions(before=now - timedelta(hours=1, minutes=30))
    older_ids = {m.session_id for m in older}
    assert "s0" not in older_ids
    assert "s1" not in older_ids
    assert "s4" in older_ids


def test_session_id_is_uuid7() -> None:
    sid = new_session_id()
    # 36 chars, hyphen-separated, version nibble == 7, variant '10'
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        sid,
    )


def test_session_ids_are_time_ordered() -> None:
    """UUIDv7 sorts lexicographically by ms timestamp prefix. Within the same
    ms the random tail can re-order — sleep enough to roll into a new ms."""
    import time

    a = new_session_id()
    time.sleep(0.005)
    b = new_session_id()
    # Compare the 48-bit timestamp prefix (first 12 hex chars).
    assert a[:13] <= b[:13]


def test_assistant_tool_calls_are_searchable(store: SessionStore) -> None:
    meta = _meta()
    store.open_session(meta)
    store.append_turn(
        meta.session_id,
        {
            "role": "assistant",
            "content": "running it",
            "tool_calls": [
                {
                    "function": {
                        "name": "Bash",
                        "arguments": {"command": "ls /tmp/exoticdir"},
                    },
                }
            ],
        },
    )
    hits = store.search("exoticdir")
    assert len(hits) == 1
    assert hits[0].role == "assistant"


def test_search_includes_surrounding(store: SessionStore) -> None:
    meta = _meta()
    store.open_session(meta)
    store.append_turn(meta.session_id, {"role": "user", "content": "context before"})
    store.append_turn(meta.session_id, {"role": "user", "content": "find the needle here"})
    store.append_turn(meta.session_id, {"role": "user", "content": "context after"})
    hits = store.search("needle")
    assert len(hits) == 1
    surrounding = hits[0].surrounding
    contents = [s["content"] for s in surrounding]
    assert contents == ["context before", "find the needle here", "context after"]


def test_search_returns_empty_when_no_match(store: SessionStore) -> None:
    meta = _meta()
    store.open_session(meta)
    store.append_turn(meta.session_id, {"role": "user", "content": "hello"})
    assert store.search("nonexistent_term_zzz") == []


# -- child / parent lineage ----------------------------------------------


def test_child_sessions_have_parent_id(store: SessionStore) -> None:
    parent = _meta("parent")
    child = _meta("child", parent_session_id="parent")
    store.open_session(parent)
    store.open_session(child)
    listed = store.list_sessions()
    by_id = {m.session_id: m for m in listed}
    assert by_id["child"].parent_session_id == "parent"
    assert by_id["parent"].parent_session_id is None


def test_children_query_returns_forks(store: SessionStore) -> None:
    parent = _meta("parent2")
    a = _meta("fork-a", parent_session_id="parent2")
    b = _meta("fork-b", parent_session_id="parent2")
    other = _meta("other")  # unrelated
    store.open_session(parent)
    store.open_session(a)
    store.open_session(b)
    store.open_session(other)
    kids = store.children("parent2")
    ids = {m.session_id for m in kids}
    assert ids == {"fork-a", "fork-b"}


def test_children_persists_in_meta_json(store: SessionStore, profile_dir: Path) -> None:
    """parent_session_id round-trips through the meta.json sidecar."""
    store.open_session(_meta("p"))
    store.open_session(_meta("c", parent_session_id="p"))
    sidecar = profile_dir / "sessions" / "c.meta.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["parent_session_id"] == "p"
