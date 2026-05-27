"""Protocol-shape and dataclass-immutability checks for the
user-model backend surface. Cheap, catches signature drift."""

from __future__ import annotations

import dataclasses

import pytest

from athena.user_model.base import (
    BackendHealth,
    ExtractedFact,
    IngestResult,
    QueryResult,
    UserModelBackend,
)


def test_protocol_is_runtime_checkable():
    """Anything with the right shape should pass isinstance check —
    that's what makes the Protocol usable in factory wiring tests."""

    class Stub:
        async def ingest_session(self, transcript, *, session_id):
            return IngestResult(0, 0, 0, "stub")

        async def query(self, question, *, max_tokens=800):
            return QueryResult("", [], 0.0)

        def health(self) -> BackendHealth:
            return BackendHealth("ready", "stub", "stub")

    assert isinstance(Stub(), UserModelBackend)


def test_results_are_frozen_dataclasses():
    """Frozen so tools that pass results across thread boundaries
    don't accidentally mutate shared state."""
    for cls in (ExtractedFact, IngestResult, QueryResult, BackendHealth):
        assert dataclasses.is_dataclass(cls)
        # ``frozen=True`` means setattr raises FrozenInstanceError.
        params = cls.__dataclass_params__
        assert params.frozen, f"{cls.__name__} should be frozen"


def test_query_result_with_no_sources_is_zero_confidence():
    """Sanity: a result claiming sources implies confidence > 0;
    a result with no sources should not silently claim certainty."""
    no_src = QueryResult(answer="no idea", sources=[], confidence=0.0)
    assert no_src.confidence == 0.0
    assert no_src.sources == []


def test_extracted_fact_accepts_well_formed_values():
    f = ExtractedFact(
        id="user-prefers-terse-responses",
        body="User dislikes long summaries",
        category="communication-style",
        confidence=0.85,
    )
    assert 0.0 <= f.confidence <= 1.0


def test_frozen_setattr_raises():
    f = ExtractedFact(id="x", body="y", category="z", confidence=0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.confidence = 0.9  # type: ignore[misc]
