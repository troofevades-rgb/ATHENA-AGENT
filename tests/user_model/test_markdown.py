"""Round-trip tests for the MarkdownUserModel — ingest writes
markdown files, query reads them back via a fake LLM that returns
canned text. Tests are LLM-free."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.user_model.markdown import (
    MarkdownUserModel,
    _parse_extracted_facts,
    _split_sources,
)


# ---- helpers ----------------------------------------------------


def make_fake_llm(*, ingest_json: str = "[]", query_text: str = "answer\nSOURCES: none"):
    """Build an async LLM stub that returns different canned text
    based on which system prompt was sent (extraction vs query)."""

    async def _call(system: str, user: str) -> str:
        if "STRICT JSON" in system:
            return ingest_json
        return query_text

    return _call


# ---- ingest ------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_writes_one_file_per_fact(tmp_path: Path):
    facts = [
        {
            "id": "user-likes-pytest",
            "body": "User reaches for pytest, not unittest",
            "category": "tech-stack",
            "confidence": 0.9,
        },
        {
            "id": "project-uses-ollama",
            "body": "athena runs against a local Ollama daemon",
            "category": "project-context",
            "confidence": 0.95,
        },
    ]
    backend = MarkdownUserModel(
        storage_dir=tmp_path,
        llm_call=make_fake_llm(ingest_json=json.dumps(facts)),
    )
    result = await backend.ingest_session([{"role": "user", "content": "hi"}], session_id="s1")
    assert result.facts_added == 2
    assert result.facts_updated == 0
    assert (tmp_path / "user-likes-pytest.md").exists()
    assert (tmp_path / "project-uses-ollama.md").exists()
    # INDEX.md gets refreshed.
    assert (tmp_path / "INDEX.md").exists()


@pytest.mark.asyncio
async def test_ingest_updates_existing_id(tmp_path: Path):
    """Re-extracting the same ID counts as an update, not a new fact."""
    first = [
        {
            "id": "user-prefers-terse",
            "body": "v1",
            "category": "communication-style",
            "confidence": 0.7,
        }
    ]
    backend = MarkdownUserModel(
        storage_dir=tmp_path,
        llm_call=make_fake_llm(ingest_json=json.dumps(first)),
    )
    r1 = await backend.ingest_session([], session_id="s1")
    assert r1.facts_added == 1 and r1.facts_updated == 0

    second = [
        {
            "id": "user-prefers-terse",
            "body": "v2 (refined)",
            "category": "communication-style",
            "confidence": 0.9,
        }
    ]
    backend._llm = make_fake_llm(ingest_json=json.dumps(second))  # type: ignore[attr-defined]
    r2 = await backend.ingest_session([], session_id="s2")
    assert r2.facts_added == 0 and r2.facts_updated == 1

    # Body on disk reflects the v2 content.
    body = (tmp_path / "user-prefers-terse.md").read_text(encoding="utf-8")
    assert "v2 (refined)" in body
    assert "v1" not in body


@pytest.mark.asyncio
async def test_ingest_drops_invalid_id(tmp_path: Path):
    """Malformed IDs (e.g. with slashes) shouldn't crash extraction
    or write files outside the storage dir."""
    facts = [
        {
            "id": "../escaping-attempt",
            "body": "evil",
            "category": "x",
            "confidence": 0.5,
        },
        {
            "id": "ok-id",
            "body": "good",
            "category": "x",
            "confidence": 0.5,
        },
    ]
    backend = MarkdownUserModel(
        storage_dir=tmp_path,
        llm_call=make_fake_llm(ingest_json=json.dumps(facts)),
    )
    result = await backend.ingest_session([], session_id="s1")
    assert result.facts_added == 1
    assert (tmp_path / "ok-id.md").exists()
    # The escaping attempt was dropped — nothing written upstream.
    assert not (tmp_path.parent / "escaping-attempt.md").exists()


@pytest.mark.asyncio
async def test_ingest_handles_extractor_error(tmp_path: Path):
    """A blowing-up LLM yields a zero-result, not a crash. Critical
    for the fire-and-forget compact hook."""

    async def _boom(system, user):
        raise RuntimeError("ollama is on vacation")

    backend = MarkdownUserModel(storage_dir=tmp_path, llm_call=_boom)
    result = await backend.ingest_session([], session_id="s")
    assert result.facts_added == 0
    assert result.facts_updated == 0


@pytest.mark.asyncio
async def test_ingest_strips_markdown_fence(tmp_path: Path):
    """Extractor models love adding ```json fences despite
    instructions. Tolerant parser must strip them."""
    fenced = (
        "```json\n"
        '[{"id":"a-fact","body":"b","category":"c","confidence":0.5}]\n'
        "```"
    )
    backend = MarkdownUserModel(
        storage_dir=tmp_path,
        llm_call=make_fake_llm(ingest_json=fenced),
    )
    result = await backend.ingest_session([], session_id="s")
    assert result.facts_added == 1
    assert (tmp_path / "a-fact.md").exists()


# ---- query -------------------------------------------------------


@pytest.mark.asyncio
async def test_query_returns_empty_when_no_facts(tmp_path: Path):
    backend = MarkdownUserModel(storage_dir=tmp_path, llm_call=make_fake_llm())
    result = await backend.query("anything")
    assert "no facts" in result.answer.lower()
    assert result.sources == []
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_query_parses_sources_line(tmp_path: Path):
    # Seed a fact file so the load path doesn't short-circuit.
    (tmp_path / "f1.md").write_text(
        "---\nid: f1\ncategory: x\nsource: auto\n---\n\nbody1\n",
        encoding="utf-8",
    )
    backend = MarkdownUserModel(
        storage_dir=tmp_path,
        llm_call=make_fake_llm(
            query_text="The user likes pytest.\nSOURCES: f1, f2"
        ),
    )
    result = await backend.query("does user like pytest?")
    assert result.answer == "The user likes pytest."
    assert result.sources == ["f1", "f2"]
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_query_handles_no_sources(tmp_path: Path):
    """'SOURCES: none' should return empty sources list +
    zero confidence — the answer might still be useful prose
    ('I don't know') but it's not citing facts."""
    (tmp_path / "f1.md").write_text(
        "---\nid: f1\ncategory: x\nsource: auto\n---\n\nbody1\n",
        encoding="utf-8",
    )
    backend = MarkdownUserModel(
        storage_dir=tmp_path,
        llm_call=make_fake_llm(query_text="no clue\nSOURCES: none"),
    )
    result = await backend.query("?")
    assert result.sources == []
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_query_includes_user_authored_when_dir_provided(tmp_path: Path):
    """When ``authored_memory_dir`` is set, query reads facts
    from both stores. Sources should reflect both."""
    auto_dir = tmp_path / "auto"
    user_dir = tmp_path / "user"
    auto_dir.mkdir()
    user_dir.mkdir()
    (auto_dir / "auto1.md").write_text(
        "---\nid: auto1\nsource: auto\n---\n\nauto fact body\n",
        encoding="utf-8",
    )
    (user_dir / "user1.md").write_text(
        "---\nname: User1\ntype: user\n---\n\nuser fact body\n",
        encoding="utf-8",
    )

    captured: dict = {}

    async def _capture_llm(system: str, user: str) -> str:
        captured["prompt"] = user
        return "merged\nSOURCES: auto1, user1"

    backend = MarkdownUserModel(
        storage_dir=auto_dir,
        llm_call=_capture_llm,
        authored_memory_dir=user_dir,
    )
    result = await backend.query("?")
    # Both provenance tags must appear in the synthesized prompt
    # the LLM saw — proves the backend is mixing stores correctly.
    assert "[auto]" in captured["prompt"]
    assert "[user]" in captured["prompt"]
    assert "auto1" in result.sources
    assert "user1" in result.sources


# ---- health ------------------------------------------------------


def test_health_ready_when_storage_creatable(tmp_path: Path):
    backend = MarkdownUserModel(
        storage_dir=tmp_path / "new",
        llm_call=make_fake_llm(),
    )
    h = backend.health()
    assert h.status == "ready"
    assert h.backend == "markdown"


# ---- module-level helpers ----------------------------------------


def test_parse_extracted_facts_tolerates_garbage():
    assert _parse_extracted_facts("not json at all") == []
    assert _parse_extracted_facts("{}") == []  # dict, not list
    assert _parse_extracted_facts("[123, null, {}]") == []  # malformed items


def test_split_sources_handles_missing_sources_line():
    answer, sources = _split_sources("just an answer with no footer")
    assert answer == "just an answer with no footer"
    assert sources == []


def test_split_sources_trims_whitespace_in_id_list():
    answer, sources = _split_sources("body\nSOURCES:  a ,  b , c  ")
    assert sources == ["a", "b", "c"]
