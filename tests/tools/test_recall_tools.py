"""Tests for the search_sessions recall tool."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.sessions.store import SessionMeta, SessionStore, new_session_id
from athena.tools import recall_tools


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    d = tmp_path / "profiles" / "default"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def seeded_store(profile_dir: Path):
    store = SessionStore(profile_dir)
    sid1 = new_session_id()
    sid2 = new_session_id()
    store.open_session(
        SessionMeta(session_id=sid1, profile="default", model="qwen", workspace="/proj")
    )
    store.append_turn(sid1, {"role": "user", "content": "context before"})
    store.append_turn(sid1, {"role": "user", "content": "find the needle here"})
    store.append_turn(sid1, {"role": "user", "content": "context after"})

    store.open_session(
        SessionMeta(session_id=sid2, profile="default", model="qwen", workspace="/other")
    )
    store.append_turn(sid2, {"role": "user", "content": "the needle in another haystack"})

    yield store, sid1, sid2
    store.close()


def _fake_agent(store: SessionStore, workspace: str = "/proj") -> SimpleNamespace:
    return SimpleNamespace(session_store=store, workspace=workspace)


def test_search_sessions_returns_top_k(seeded_store, monkeypatch) -> None:
    store, sid1, sid2 = seeded_store
    monkeypatch.setattr(
        "athena.agent.core.get_current_agent",
        lambda: _fake_agent(store, workspace="/proj"),
    )
    out = recall_tools.search_sessions("needle", k=5)
    assert "Found 1" in out  # workspace defaults to /proj → only sid1 matches
    assert sid1 in out
    assert sid2 not in out


def test_search_sessions_filters_workspace_by_default(seeded_store, monkeypatch) -> None:
    store, sid1, _sid2 = seeded_store
    monkeypatch.setattr(
        "athena.agent.core.get_current_agent",
        lambda: _fake_agent(store, workspace="/proj"),
    )
    out = recall_tools.search_sessions("needle")
    assert "/proj" or sid1 in out
    assert "Found 1" in out


def test_search_sessions_empty_workspace_searches_globally(seeded_store, monkeypatch) -> None:
    store, sid1, sid2 = seeded_store
    monkeypatch.setattr(
        "athena.agent.core.get_current_agent",
        lambda: _fake_agent(store, workspace="/proj"),
    )
    out = recall_tools.search_sessions("needle", workspace="")
    assert sid1 in out
    assert sid2 in out
    assert "Found 2" in out


def test_search_sessions_includes_surrounding_context(seeded_store, monkeypatch) -> None:
    store, sid1, _sid2 = seeded_store
    monkeypatch.setattr(
        "athena.agent.core.get_current_agent",
        lambda: _fake_agent(store),
    )
    out = recall_tools.search_sessions("needle", k=1)
    assert "context before" in out
    assert "context after" in out
    assert "▶" in out  # the hit row gets the marker


def test_search_sessions_no_matches_message(seeded_store, monkeypatch) -> None:
    store, _sid1, _sid2 = seeded_store
    monkeypatch.setattr(
        "athena.agent.core.get_current_agent",
        lambda: _fake_agent(store),
    )
    out = recall_tools.search_sessions("zzz_no_such_term")
    assert "No matches" in out


def test_search_sessions_without_active_agent(monkeypatch) -> None:
    monkeypatch.setattr("athena.agent.core.get_current_agent", lambda: None)
    out = recall_tools.search_sessions("anything")
    assert "ERROR" in out
