"""Tests for ``athena.recall.manager`` — doc-id conventions + the
embed-on-write contract.

Two critical invariants pinned here:

  1. **Silent best-effort contract.** ``record_turn`` and
     ``record_memory_entry`` must NEVER raise. The recall layer is
     auxiliary; an embed failure must not break the agent loop.
  2. **Doc-id roundtrip.** ``session_doc_id`` and
     ``parse_session_doc_id`` are inverses. Mixing memory ids into
     the session parser must return None, not garbage.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from athena.recall.manager import (
    build_vector_store,
    get_active_vector_store,
    memory_doc_id,
    parse_session_doc_id,
    record_memory_entry,
    record_turn,
    session_doc_id,
    set_active_vector_store,
)


# ---------------------------------------------------------------------------
# Doc-id construction
# ---------------------------------------------------------------------------


def test_session_doc_id_format() -> None:
    assert session_doc_id("abc123", 0) == "abc123#0"
    assert session_doc_id("abc123", 42) == "abc123#42"


def test_memory_doc_id_format() -> None:
    assert memory_doc_id("default", "user_role") == "memory:default:user_role"


def test_session_doc_id_roundtrip() -> None:
    for sid, idx in [("a", 0), ("session-uuid-here", 17), ("x", 999)]:
        encoded = session_doc_id(sid, idx)
        assert parse_session_doc_id(encoded) == (sid, idx)


# ---------------------------------------------------------------------------
# parse_session_doc_id — edge cases (the parser must not produce false hits)
# ---------------------------------------------------------------------------


def test_parse_session_doc_id_rejects_memory_ids() -> None:
    """Memory IDs use ``memory:profile:name`` shape. The session
    parser must NOT try to interpret them — would produce
    nonsensical (profile, name)→(sid, idx) results."""
    assert parse_session_doc_id("memory:default:user_role") is None
    assert parse_session_doc_id("memory:p1:x#5") is None  # has # but is memory


def test_parse_session_doc_id_rejects_no_hash() -> None:
    assert parse_session_doc_id("abc123") is None
    assert parse_session_doc_id("") is None


def test_parse_session_doc_id_rejects_non_int_turn_index() -> None:
    """Malformed turn index → None. Don't crash on a bad
    on-disk vector that survived a refactor."""
    assert parse_session_doc_id("session#not-a-number") is None
    assert parse_session_doc_id("session#") is None


def test_parse_session_doc_id_rejects_empty_session_part() -> None:
    """``#5`` (empty session id) is malformed — must reject."""
    assert parse_session_doc_id("#5") is None


def test_parse_session_doc_id_handles_session_id_with_hashes() -> None:
    """Some session ids could contain ``#`` if a future scheme
    permits it. ``rpartition`` takes the LAST ``#`` as the turn
    delimiter — pin that this is the intended behavior."""
    out = parse_session_doc_id("weird#id#3")
    assert out == ("weird#id", 3)


# ---------------------------------------------------------------------------
# Active-store ContextVar
# ---------------------------------------------------------------------------


def test_get_active_returns_none_by_default() -> None:
    """Outside a session, no store is active — recall tools
    handle this as no-semantic-mode rather than crashing."""
    # Reset to baseline (other tests may have polluted)
    set_active_vector_store(None)
    assert get_active_vector_store() is None


def test_set_then_get_returns_same_object() -> None:
    set_active_vector_store(None)  # clean state
    try:
        sentinel = object()  # use a placeholder VectorStore stand-in
        set_active_vector_store(sentinel)  # type: ignore[arg-type]
        assert get_active_vector_store() is sentinel
    finally:
        set_active_vector_store(None)


def test_active_store_is_context_isolated() -> None:
    """ContextVar means a fork's set doesn't bleed into the
    parent's context. Pin the isolation."""
    set_active_vector_store(None)
    parent_sentinel = object()
    set_active_vector_store(parent_sentinel)  # type: ignore[arg-type]

    def _fork():
        # Fork sees parent's value, can set its own without
        # affecting parent
        assert get_active_vector_store() is parent_sentinel
        set_active_vector_store(object())  # type: ignore[arg-type]

    ctx = contextvars.copy_context()
    ctx.run(_fork)
    # Parent's store unchanged
    assert get_active_vector_store() is parent_sentinel
    set_active_vector_store(None)


# ---------------------------------------------------------------------------
# build_vector_store — config gating
# ---------------------------------------------------------------------------


@dataclass
class _Cfg:
    semantic_recall_enabled: bool = True
    embedding_model: str | None = None
    vector_store_path: str | None = None


def test_build_returns_none_when_semantic_recall_disabled(
    tmp_path: Path,
) -> None:
    """Explicit opt-out via ``cfg.semantic_recall_enabled=False``
    short-circuits regardless of whether an embedder exists."""
    out = build_vector_store(
        cfg=_Cfg(semantic_recall_enabled=False),
        profile_dir=tmp_path,
    )
    assert out is None


def test_build_returns_none_when_no_embedder_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resolve_embedder`` returning None → build returns None
    too. Recall degrades to keyword-only silently."""
    from athena.recall import manager as _m
    monkeypatch.setattr(_m, "resolve_embedder", lambda *, cfg: None)
    out = build_vector_store(cfg=_Cfg(), profile_dir=tmp_path)
    assert out is None


# ---------------------------------------------------------------------------
# record_turn — silent best-effort contract
# ---------------------------------------------------------------------------


class _RecordingStore:
    """Stand-in vector store that records calls to .add()."""
    def __init__(self):
        self.added: list[dict] = []

    def add(self, *, doc_id, text, workspace, text_preview):
        self.added.append({
            "doc_id": doc_id, "text": text,
            "workspace": workspace, "text_preview": text_preview,
        })


@pytest.fixture
def _store():
    store = _RecordingStore()
    set_active_vector_store(store)  # type: ignore[arg-type]
    yield store
    set_active_vector_store(None)


def test_record_turn_no_store_is_silent_noop() -> None:
    """Outside a session (no active store) — must not raise."""
    set_active_vector_store(None)
    record_turn(
        session_id="s", turn_index=0, role="user",
        content="hi", workspace="/tmp",
    )  # no exception = pass


def test_record_turn_skips_tool_role(_store: _RecordingStore) -> None:
    """Tool results pollute the vector store with verbose JSON;
    skip them. Same for system messages."""
    record_turn(
        session_id="s", turn_index=0, role="tool",
        content="result blob", workspace="/tmp",
    )
    record_turn(
        session_id="s", turn_index=1, role="system",
        content="system msg", workspace="/tmp",
    )
    assert _store.added == []


def test_record_turn_embeds_user_messages(_store: _RecordingStore) -> None:
    record_turn(
        session_id="s", turn_index=0, role="user",
        content="what is in this file?", workspace="/ws",
    )
    assert len(_store.added) == 1
    assert _store.added[0]["doc_id"] == "s#0"
    assert _store.added[0]["text"] == "what is in this file?"
    assert _store.added[0]["workspace"] == "/ws"


def test_record_turn_embeds_assistant_messages(_store: _RecordingStore) -> None:
    record_turn(
        session_id="s", turn_index=1, role="assistant",
        content="the file defines class Foo", workspace="/ws",
    )
    assert len(_store.added) == 1


def test_record_turn_skips_empty_content(_store: _RecordingStore) -> None:
    """Empty / whitespace-only content is noise."""
    for empty in ("", "   ", "\n\n\t"):
        record_turn(
            session_id="s", turn_index=0, role="user",
            content=empty, workspace="/ws",
        )
    assert _store.added == []


def test_record_turn_handles_anthropic_list_content(
    _store: _RecordingStore,
) -> None:
    """Anthropic multimodal: content is a list of dict blocks.
    Text blocks are joined and embedded; non-text blocks are
    skipped silently."""
    content = [
        {"type": "text", "text": "first text"},
        {"type": "image", "source": "..."},
        {"type": "text", "text": "second text"},
    ]
    record_turn(
        session_id="s", turn_index=0, role="user",
        content=content, workspace="/ws",  # type: ignore[arg-type]
    )
    assert len(_store.added) == 1
    assert "first text" in _store.added[0]["text"]
    assert "second text" in _store.added[0]["text"]


def test_record_turn_handles_list_content_with_only_images(
    _store: _RecordingStore,
) -> None:
    """List content with no text blocks → empty join → no add."""
    content = [
        {"type": "image", "source": "..."},
        {"type": "image", "source": "..."},
    ]
    record_turn(
        session_id="s", turn_index=0, role="user",
        content=content, workspace="/ws",  # type: ignore[arg-type]
    )
    assert _store.added == []


def test_record_turn_truncates_preview_at_200_chars(
    _store: _RecordingStore,
) -> None:
    """text_preview is shown in the UI / used for keyword search;
    truncate at 200 chars so the index file doesn't bloat."""
    big = "x" * 500
    record_turn(
        session_id="s", turn_index=0, role="user",
        content=big, workspace="/ws",
    )
    assert len(_store.added[0]["text_preview"]) == 200


def test_record_turn_swallows_store_add_exception() -> None:
    """The silent-best-effort contract: if store.add raises (full
    disk, embedding API down, etc.) the agent loop must NOT see
    it. Pin via a store that always raises."""
    class _BombStore:
        def add(self, **kw):
            raise RuntimeError("simulated embed failure")

    set_active_vector_store(_BombStore())  # type: ignore[arg-type]
    try:
        # Must not raise
        record_turn(
            session_id="s", turn_index=0, role="user",
            content="hi", workspace="/ws",
        )
    finally:
        set_active_vector_store(None)


# ---------------------------------------------------------------------------
# record_memory_entry
# ---------------------------------------------------------------------------


def test_record_memory_entry_no_store_silent() -> None:
    set_active_vector_store(None)
    record_memory_entry(profile="default", name="x", content="hi")


def test_record_memory_entry_writes_with_memory_doc_id(
    _store: _RecordingStore,
) -> None:
    record_memory_entry(
        profile="default", name="user_role",
        content="user is a data scientist", workspace="/ws",
    )
    assert _store.added[0]["doc_id"] == "memory:default:user_role"


def test_record_memory_entry_skips_empty() -> None:
    set_active_vector_store(_RecordingStore())
    try:
        record_memory_entry(profile="p", name="n", content="")
        record_memory_entry(profile="p", name="n", content="   ")
        store = get_active_vector_store()
        assert store.added == []  # type: ignore[attr-defined]
    finally:
        set_active_vector_store(None)


def test_record_memory_entry_swallows_exceptions() -> None:
    """Silent contract — memory writes never break the caller."""
    class _BombStore:
        def add(self, **kw): raise OSError("disk full")

    set_active_vector_store(_BombStore())  # type: ignore[arg-type]
    try:
        record_memory_entry(profile="p", name="n", content="something")
    finally:
        set_active_vector_store(None)
