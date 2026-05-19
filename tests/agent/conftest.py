"""Fixtures for the agent core unit-test suite (T1-04).

Every test in this directory is hermetic: no Ollama, no real network,
no real ``~/.athena/``. ``FakeProvider`` yields a scripted sequence
of :class:`athena.providers.base.StreamChunk` so the loop under test
sees deterministic input.

See ``_PLAN.md`` for why the contracts here look the way they do —
in particular, why ``stream_chat`` is sync (not async like the spec
skeleton assumed).
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from athena.providers.base import Provider, StreamChunk


# ---------------------------------------------------------------------
# FakeProvider — sync iterator of pre-baked StreamChunks
# ---------------------------------------------------------------------


class FakeProvider(Provider):
    """Synchronous stand-in for a real provider.

    Construct from a list of scenarios. Each scenario is a list of
    StreamChunk-shaped dicts (``{"kind": ..., "payload": ...}``).
    Each call to :meth:`stream_chat` consumes one scenario and yields
    its chunks. Exhaustion raises so a runaway loop fails loudly
    instead of hanging.

    ``call_history`` records every ``(messages, tools)`` tuple so
    tests can assert what the loop sent.
    """

    name = "fake"
    requires_api_key = False

    def __init__(self, scenarios: list[list[dict[str, Any]]] | None = None) -> None:
        super().__init__(api_key=None)
        self._scenarios: list[list[dict[str, Any]]] = list(scenarios or [])
        self._idx = 0
        self.call_history: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    # ---- programming API used by tests ----

    def add_scenario(self, chunks: list[dict[str, Any]]) -> None:
        """Append one streaming scenario. Lets tests build scripts
        without re-constructing the provider."""
        self._scenarios.append(chunks)

    @classmethod
    def from_fixture(cls, path: Path) -> FakeProvider:
        """Load a JSONL fixture. Lines starting with ``//`` are
        treated as comments and skipped (JSONL doesn't have comments
        natively, but our fixture files use them for readability)."""
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        chunks: list[dict[str, Any]] = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            chunks.append(json.loads(stripped))
        # Group by optional "scenario" key — chunks with the same
        # scenario id stream together as one call.
        scenarios: dict[int, list[dict[str, Any]]] = {}
        for c in chunks:
            sid = c.pop("scenario", 0)
            scenarios.setdefault(sid, []).append(c)
        ordered = [scenarios[k] for k in sorted(scenarios.keys())]
        return cls(ordered)

    # ---- Provider ABC implementation ----

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        self.call_history.append((list(messages), tools))
        if self._idx >= len(self._scenarios):
            raise RuntimeError(
                f"FakeProvider exhausted: loop tried scenario "
                f"#{self._idx} but only {len(self._scenarios)} were "
                "scripted. Either the test under-supplied scenarios "
                "or the agent looped further than expected."
            )
        scenario = self._scenarios[self._idx]
        self._idx += 1
        for chunk_dict in scenario:
            yield StreamChunk(**chunk_dict)

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        # Tests script tool calls via the tool_call StreamChunk path,
        # not via post-hoc parsing of content. This is a no-op.
        return content, []

    def list_models(self) -> list[str]:
        return ["fake-model"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def fake_provider() -> FakeProvider:
    """Empty fake provider; tests call ``add_scenario`` per scenario
    they want to script."""
    return FakeProvider([])


# Re-export the top-level ``isolated_home`` fixture under the
# ``isolated_profile_dir`` name the spec skeleton uses. Both point at
# the same tmp_path-rooted home; this just keeps spec-aligned tests
# importable without rewriting them.
@pytest.fixture
def isolated_profile_dir(isolated_home: Path) -> Path:
    """Tmp-rooted ``~/.athena`` for the test's duration."""
    return isolated_home / ".athena"


@pytest.fixture
def thread_baseline():
    """Snapshot thread IDs before the test; assert no fork-spawned
    daemon threads leak past test exit. Forks join() before
    returning so this should be a no-op for well-behaved tests."""
    before = {t.ident for t in threading.enumerate() if t.ident is not None}
    yield before
    # Daemon threads need a moment to wind down after the parent
    # join() returns. 100ms is generous for our fork shape.
    time.sleep(0.1)
    after = {t.ident for t in threading.enumerate() if t.ident is not None}
    leaked = after - before
    # Filter out test-runner workers / pytest-xdist internals that
    # legitimately predate this test's window.
    suspicious = {t for t in threading.enumerate() if t.ident in leaked and t.daemon}
    suspect_names = [t.name for t in suspicious if t.name.startswith("athena-")]
    assert not suspect_names, (
        f"Test leaked athena-prefixed daemon threads: {suspect_names}"
    )


@pytest.fixture
def captured_streams(capsys: pytest.CaptureFixture[str]):
    """Returns the (stdout, stderr) captured during the test."""
    return capsys


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def make_chunk(kind: str, payload: Any) -> dict[str, Any]:
    """Tiny constructor for inline StreamChunk dicts in tests."""
    return {"kind": kind, "payload": payload}
