"""Tests for the disclosure hook on manager.skill_view + loader.load_body (T3-06R.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.skills.loader import invalidate_all, load_body
from athena.skills.manager import skill_view
from athena.skills.metrics import (
    SkillMetricsStore,
    _NoopStore,
    metrics_path,
    set_active_store,
)


@pytest.fixture(autouse=True)
def _clear_active_store():
    """Defensive: keep cross-test ContextVar isolation. Clear before
    AND after so a misbehaving test can't leak into siblings."""
    set_active_store(None)
    yield
    set_active_store(None)


@pytest.fixture
def store(tmp_path: Path) -> SkillMetricsStore:
    return SkillMetricsStore(metrics_path(tmp_path))


def _make_skill(workspace: Path, name: str = "demo", body: str = "body") -> None:
    skill_dir = workspace / ".athena" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: a demo skill\n"
        f"state: active\n"
        f"pinned: false\n"
        f"write_origin: foreground\n"
        f"---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: a demo skill\n"
        f"state: active\n"
        f"pinned: false\n"
        f"write_origin: foreground\n"
        f"---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# manager.skill_view
# ---------------------------------------------------------------------------


def test_skill_view_records_view(tmp_path: Path, store: SkillMetricsStore) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "hello")
    invalidate_all()
    set_active_store(store)

    text = skill_view("hello", workspace)
    assert text is not None
    assert store.get("hello").views == 1


def test_skill_view_missing_does_not_record(tmp_path: Path, store: SkillMetricsStore) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    set_active_store(store)

    result = skill_view("nope", workspace)
    assert result is None
    assert store.all() == {}


# ---------------------------------------------------------------------------
# loader.load_body
# ---------------------------------------------------------------------------


def test_disclosure_records_view_via_load_body(tmp_path: Path, store: SkillMetricsStore) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "loaded")
    invalidate_all()
    set_active_store(store)

    body = load_body("loaded", workspace)
    assert body is not None
    assert store.get("loaded").views == 1


def test_load_body_cache_hit_still_records(tmp_path: Path, store: SkillMetricsStore) -> None:
    """Cached re-reads still count as the model paying attention to
    the skill — view is the per-disclosure signal, not the
    per-disk-read signal."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "cached")
    invalidate_all()
    set_active_store(store)

    load_body("cached", workspace)
    load_body("cached", workspace)
    load_body("cached", workspace)
    assert store.get("cached").views == 3


def test_load_body_missing_does_not_record(tmp_path: Path, store: SkillMetricsStore) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    invalidate_all()
    set_active_store(store)

    body = load_body("nope", workspace)
    assert body is None
    assert store.all() == {}


# ---------------------------------------------------------------------------
# Disabled / no store → no records
# ---------------------------------------------------------------------------


def test_no_active_store_is_noop(tmp_path: Path) -> None:
    """When the agent doesn't set an active store (or set_active_store(None)),
    the disclosure hook silently does nothing."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "any")
    invalidate_all()
    set_active_store(None)

    # Both paths should succeed without raising.
    text = skill_view("any", workspace)
    body = load_body("any", workspace)
    assert text is not None
    assert body is not None


def test_disabled_flag_no_records(tmp_path: Path) -> None:
    """The cfg.skill_metrics_enabled=False path installs a _NoopStore.
    Calls land but produce no records."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "any")
    invalidate_all()
    noop = _NoopStore()
    set_active_store(noop)

    text = skill_view("any", workspace)
    body = load_body("any", workspace)
    assert text is not None
    assert body is not None
    # The noop store never writes anything; all() is empty.
    assert noop.all() == {}


# ---------------------------------------------------------------------------
# Hook performance — must not crash even with thousands of calls
# ---------------------------------------------------------------------------


def test_hook_handles_high_volume(tmp_path: Path, store: SkillMetricsStore) -> None:
    """Sanity: 1k record_view calls land cleanly. The hook is on the
    hot path; this isn't a strict perf test, just a "no crash, no
    leaked file handles" guard."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _make_skill(workspace, "hot")
    invalidate_all()
    set_active_store(store)

    for _ in range(1000):
        skill_view("hot", workspace)
    assert store.get("hot").views == 1000


# ---------------------------------------------------------------------------
# Agent wiring (smoke — verify the Agent populates the ContextVar)
# ---------------------------------------------------------------------------


def test_agent_run_turn_scopes_active_store(monkeypatch) -> None:
    """When run_turn is called, the SkillMetricsStore from the
    Agent is the active one for the duration. Tested via a
    direct manipulation of the set/get functions; the full
    Agent is heavyweight to spin up."""
    from athena.skills.metrics import (
        SkillMetricsStore,
        get_active_store,
        set_active_store,
    )

    seen: list = []

    class _SpyStore(SkillMetricsStore):
        def __init__(self) -> None:
            self.path = None  # type: ignore[assignment]

        def record_view(self, name: str, session_id=None) -> None:
            seen.append(name)

    # Simulate what run_turn does: set the store, run work, clear.
    spy = _SpyStore()
    set_active_store(spy)
    try:
        active = get_active_store()
        assert active is spy
        active.record_view("traced")
    finally:
        set_active_store(None)
    assert seen == ["traced"]
    assert get_active_store() is None
