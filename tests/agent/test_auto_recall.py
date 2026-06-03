"""Auto-recall: retrieve relevant prior turns/memory and inject them as
an ephemeral "[recalled context]" system note at the start of a turn
(cfg.recall_auto, off by default).

Two layers:
  - VectorStore.recall(): scored snippets above a similarity floor.
  - Agent._maybe_inject_recall(): the injection, gated + replaced-per-turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk
from athena.recall.vector_store import VectorStore


class _KeywordEmbedder:
    """Deterministic stub: a 3-dim vector keyed on two keywords (+ a
    constant dim so no vector is all-zero)."""

    model_id = "kw"

    def embed(self, text: str) -> list[float]:
        t = text.lower()
        return [1.0 if "auth" in t else 0.0, 1.0 if "db" in t else 0.0, 0.1]


# ---- VectorStore.recall ---------------------------------------------------


def test_recall_returns_scored_snippets_above_threshold(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "idx.json", embedder=_KeywordEmbedder())
    store.add("d1", "auth module off-by-one", workspace="ws")
    store.add("d2", "db migration notes", workspace="ws")

    hits = store.recall("fix the auth bug", k=3, min_score=0.5, workspace="ws")

    assert len(hits) == 1  # only the auth doc clears the floor
    score, text = hits[0]
    assert score >= 0.5
    assert text == "auth module off-by-one"


def test_recall_respects_k_and_workspace(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "idx.json", embedder=_KeywordEmbedder())
    store.add("a", "auth one", workspace="ws")
    store.add("b", "auth two", workspace="ws")
    store.add("c", "auth elsewhere", workspace="other")

    hits = store.recall("auth", k=1, min_score=0.5, workspace="ws")
    assert len(hits) == 1  # capped at k, and "other" workspace excluded


def test_recall_empty_without_embedder(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "idx.json", embedder=None)
    assert store.recall("anything", k=3) == []


# ---- Agent injection ------------------------------------------------------


class _Done:
    """Completes immediately — one assistant message, no tool calls."""

    name = "done-model"
    requires_api_key = False

    def __init__(self) -> None:
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        yield StreamChunk("content", "Here is the answer.")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["done-model"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


class _FakeStore:
    """Returns canned recall hits; no-op for the write path that
    record_turn exercises during the turn."""

    def __init__(self, hits: list[tuple[float, str]]) -> None:
        self._hits = hits

    def recall(self, query: str, **kwargs: Any) -> list[tuple[float, str]]:
        return list(self._hits)

    def add(self, *args: Any, **kwargs: Any) -> None:
        return None

    def search(self, *args: Any, **kwargs: Any) -> list[str]:
        return []


def _recall_notes(agent: Agent) -> list[dict]:
    return [
        m
        for m in agent.messages
        if m.get("role") == "system" and "[recalled context]" in (m.get("content") or "")
    ]


def test_recall_injected_when_enabled(isolated_home: Path, workspace: Path) -> None:
    cfg = Config(model="done-model", recall_auto=True)
    agent = Agent(cfg, workspace, provider=_Done())
    agent._vector_store = _FakeStore([(0.9, "auth module off-by-one in verify()")])

    agent.run_turn("fix the auth bug")

    notes = _recall_notes(agent)
    assert len(notes) == 1
    assert "off-by-one" in notes[0]["content"]


def test_no_recall_when_disabled(isolated_home: Path, workspace: Path) -> None:
    cfg = Config(model="done-model", recall_auto=False)
    agent = Agent(cfg, workspace, provider=_Done())
    agent._vector_store = _FakeStore([(0.9, "should not appear")])

    agent.run_turn("hello")

    assert _recall_notes(agent) == []


def test_recall_note_replaced_not_accumulated(isolated_home: Path, workspace: Path) -> None:
    cfg = Config(model="done-model", recall_auto=True)
    agent = Agent(cfg, workspace, provider=_Done())
    agent._vector_store = _FakeStore([(0.9, "note A")])

    agent.run_turn("first")
    agent.run_turn("second")

    # Exactly one note survives — each turn drops the prior turn's.
    assert len(_recall_notes(agent)) == 1
