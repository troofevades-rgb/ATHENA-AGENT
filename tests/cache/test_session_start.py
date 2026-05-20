"""Tests for the Agent.__init__ cross-session cache wiring (T5-06.2).

Construction-time tests focus on the lookup/record dance the
Agent does at session start. The full Agent constructor is too
heavy to instantiate here, so the tests exercise the
``_init_cross_session_cache`` method directly against a minimal
agent-shaped namespace.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.agent.core import Agent
from athena.cache.cross_session import CrossSessionCache
from athena.providers.base import Capabilities, Provider


# ---------------------------------------------------------------------------
# Synthetic provider with declared caching capability
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_registry(monkeypatch):
    new: dict[str, type[Provider]] = {}
    monkeypatch.setattr("athena.providers._REGISTRY", new)
    return new


def _provider_with_caching(name: str) -> type[Provider]:
    class _P(Provider):
        pass

    _P.name = name
    _P.static_capabilities = classmethod(
        lambda cls, model=None: Capabilities(
            prompt_caching=True,
            cache_ttls_seconds=(300, 3600),
        )
    )  # type: ignore[method-assign]
    return _P


def _provider_no_caching(name: str) -> type[Provider]:
    class _P(Provider):
        pass

    _P.name = name
    _P.static_capabilities = classmethod(
        lambda cls, model=None: Capabilities()
    )  # type: ignore[method-assign]
    return _P


def _agent_double(*, tmp_path, provider_name: str, system_text: str, enabled: bool = True):
    """Build a minimal stand-in for an Agent that
    ``_init_cross_session_cache`` can run against."""
    cfg = SimpleNamespace(
        cross_session_cache_enabled=enabled,
        cache_min_prefix_tokens=0,
        cache_index_path=str(tmp_path / "ci.json"),
        profile="default",
    )
    agent = SimpleNamespace(
        cfg=cfg,
        workspace=tmp_path,
        provider=SimpleNamespace(name=provider_name),
        messages=[{"role": "system", "content": system_text}],
        cross_session_cache_entry=None,
    )
    # Bind the bound method so the synthetic agent runs the real
    # implementation.
    agent._init_cross_session_cache = Agent._init_cross_session_cache.__get__(agent)
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_session_start_records_on_miss(tmp_path, patched_registry):
    """First session in a workspace → miss → record."""
    patched_registry["anthropic"] = _provider_with_caching("anthropic")
    agent = _agent_double(
        tmp_path=tmp_path,
        provider_name="anthropic",
        system_text="X" * 200,
    )

    agent._init_cross_session_cache()
    # An entry was created on this session's record.
    assert agent.cross_session_cache_entry is not None
    cache = CrossSessionCache(
        index_path=Path(tmp_path / "ci.json"), cfg=agent.cfg
    )
    assert len(cache.all()) == 1


def test_session_start_reuses_on_hit(tmp_path, patched_registry):
    """Second session with the SAME prefix → hit (cache entry's
    created_at preserved from session 1, not bumped to now)."""
    patched_registry["anthropic"] = _provider_with_caching("anthropic")
    a1 = _agent_double(
        tmp_path=tmp_path,
        provider_name="anthropic",
        system_text="X" * 200,
    )
    a1._init_cross_session_cache()
    original = a1.cross_session_cache_entry
    assert original is not None

    a2 = _agent_double(
        tmp_path=tmp_path,
        provider_name="anthropic",
        system_text="X" * 200,
    )
    a2._init_cross_session_cache()
    assert a2.cross_session_cache_entry is not None
    assert a2.cross_session_cache_entry.prefix_hash == original.prefix_hash
    # Reused, not re-recorded — created_at unchanged.
    assert a2.cross_session_cache_entry.created_at == original.created_at


def test_skill_edit_invalidates(tmp_path, patched_registry):
    """Edit a pinned skill → next session's system prompt
    changes → prefix hash changes → that's a miss."""
    patched_registry["anthropic"] = _provider_with_caching("anthropic")
    a1 = _agent_double(
        tmp_path=tmp_path,
        provider_name="anthropic",
        system_text="X" * 200,
    )
    a1._init_cross_session_cache()
    h1 = a1.cross_session_cache_entry.prefix_hash

    # Session 2 with a different system prompt — simulating a
    # skill edit
    a2 = _agent_double(
        tmp_path=tmp_path,
        provider_name="anthropic",
        system_text=("X" * 199) + "Y",  # one byte differs
    )
    a2._init_cross_session_cache()
    h2 = a2.cross_session_cache_entry.prefix_hash
    assert h2 != h1


def test_disabled_means_no_cache_touched(tmp_path, patched_registry):
    """cross_session_cache_enabled=False → init is a no-op, no
    file written, no entry on the agent."""
    patched_registry["anthropic"] = _provider_with_caching("anthropic")
    agent = _agent_double(
        tmp_path=tmp_path,
        provider_name="anthropic",
        system_text="X" * 200,
        enabled=False,
    )
    agent._init_cross_session_cache()
    assert agent.cross_session_cache_entry is None
    assert not (tmp_path / "ci.json").exists()


def test_provider_without_caching_skips(tmp_path, patched_registry):
    """A provider with neither prompt_caching nor kv_cache_reuse
    → caching_plan is "none" → no record."""
    patched_registry["bare"] = _provider_no_caching("bare")
    agent = _agent_double(
        tmp_path=tmp_path,
        provider_name="bare",
        system_text="X" * 200,
    )
    agent._init_cross_session_cache()
    assert agent.cross_session_cache_entry is None
    assert not (tmp_path / "ci.json").exists()


def test_workspace_isolation(tmp_path, patched_registry):
    """Two different workspaces with identical system prompts
    keep distinct entries — no cross-project leakage."""
    patched_registry["anthropic"] = _provider_with_caching("anthropic")
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    proj_a.mkdir()
    proj_b.mkdir()

    a1 = _agent_double(
        tmp_path=proj_a,
        provider_name="anthropic",
        system_text="X" * 200,
    )
    # Share the index file so both sessions write to the same
    # store (simulating one user's profile).
    shared_index = tmp_path / "shared.json"
    a1.cfg.cache_index_path = str(shared_index)
    a1._init_cross_session_cache()

    a2 = _agent_double(
        tmp_path=proj_b,
        provider_name="anthropic",
        system_text="X" * 200,
    )
    a2.cfg.cache_index_path = str(shared_index)
    a2._init_cross_session_cache()

    cache = CrossSessionCache(index_path=shared_index, cfg=a1.cfg)
    entries = cache.all()
    assert len(entries) == 2
    workspaces = {e.workspace for e in entries}
    assert str(proj_a) in workspaces
    assert str(proj_b) in workspaces
