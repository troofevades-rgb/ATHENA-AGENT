"""Tests for the cross-session prompt cache (T5-06.1).

The single property that must be right is no-wrong-hits: a
changed prefix can't match a prior entry. Everything else is
optimization.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.cache.cross_session import (
    CacheEntry,
    CachingPlan,
    CrossSessionCache,
    prefix_hash,
)
from athena.providers.base import Capabilities, Provider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cfg(*, min_tokens: int = 0) -> SimpleNamespace:
    """Tests default to min_tokens=0 so any prefix size caches.
    The size-gate test sets a real minimum explicitly."""
    return SimpleNamespace(
        cross_session_cache_enabled=True,
        cache_min_prefix_tokens=min_tokens,
    )


@pytest.fixture
def cache(tmp_path):
    return CrossSessionCache(
        index_path=tmp_path / "cache_index.json",
        cfg=_cfg(),
    )


@pytest.fixture
def patched_registry(monkeypatch):
    new: dict[str, type[Provider]] = {}
    monkeypatch.setattr("athena.providers._REGISTRY", new)
    return new


def _provider(name: str, caps: Capabilities) -> type[Provider]:
    class _P(Provider):
        pass

    _P.name = name
    _P.static_capabilities = classmethod(lambda cls, model=None: caps)  # type: ignore[method-assign]
    return _P


# ---------------------------------------------------------------------------
# Hash properties
# ---------------------------------------------------------------------------


def test_prefix_hash_stable_and_sensitive():
    """Same input → same hash; one-char change → different hash."""
    a = prefix_hash("the quick brown fox")
    b = prefix_hash("the quick brown fox")
    c = prefix_hash("the quick brown fox.")
    assert a == b
    assert a != c
    # Hex digest length
    assert len(a) == 64


# ---------------------------------------------------------------------------
# Lookup correctness — the load-bearing tests
# ---------------------------------------------------------------------------


def test_lookup_miss_on_changed_prefix(cache):
    """Record one prefix, lookup a slightly-different one →
    miss. This is the no-wrong-hits guarantee."""
    cache.record(
        workspace="/proj",
        prefix_text="hello world this is the cached prefix",
        provider="anthropic",
        provider_cache_id="srv-abc",
        ttl_s=3600,
    )
    assert (
        cache.lookup(
            workspace="/proj",
            prefix_text="hello world this is the cached prefix!",  # one char added
            provider="anthropic",
        )
        is None
    )


def test_lookup_miss_on_different_workspace(cache):
    """Same prefix, different workspace → miss. Workspace is
    part of the key so a personal project's cached prefix
    doesn't leak into a work project's session."""
    cache.record(
        workspace="/proj/a",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="srv-aaa",
        ttl_s=3600,
    )
    assert (
        cache.lookup(
            workspace="/proj/b",
            prefix_text="X" * 200,
            provider="anthropic",
        )
        is None
    )


def test_lookup_miss_on_different_provider(cache):
    """Same prefix + workspace, different provider → miss. The
    provider's server-side cache id is provider-specific."""
    cache.record(
        workspace="/proj",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="srv-anth",
        ttl_s=3600,
    )
    assert (
        cache.lookup(
            workspace="/proj",
            prefix_text="X" * 200,
            provider="openai",
        )
        is None
    )


def test_lookup_hit_within_ttl(cache):
    entry = cache.record(
        workspace="/proj",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="srv-aaa",
        ttl_s=3600,
    )
    assert entry is not None
    hit = cache.lookup(
        workspace="/proj",
        prefix_text="X" * 200,
        provider="anthropic",
    )
    assert hit is not None
    assert hit.provider_cache_id == "srv-aaa"
    assert hit.prefix_hash == entry.prefix_hash


def test_lookup_miss_after_ttl(cache):
    """An expired entry is treated as a miss."""
    cache.record(
        workspace="/proj",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="srv-aaa",
        ttl_s=3600,
    )
    # Backdate the entry past its TTL.
    key = list(cache._index.keys())[0]
    cache._index[key].created_at = time.time() - 4000
    assert (
        cache.lookup(
            workspace="/proj",
            prefix_text="X" * 200,
            provider="anthropic",
        )
        is None
    )


# ---------------------------------------------------------------------------
# Caching plan — manifest-driven
# ---------------------------------------------------------------------------


def test_caching_plan_server_when_provider_supports(patched_registry, cache):
    """A provider declaring prompt_caching + cache_ttls_seconds
    yields a server-mode plan with the largest declared TTL."""
    patched_registry["anthropic"] = _provider(
        "anthropic",
        Capabilities(prompt_caching=True, cache_ttls_seconds=(300, 3600)),
    )
    plan = cache.caching_plan("anthropic")
    assert isinstance(plan, CachingPlan)
    assert plan.mode == "server"
    assert plan.ttl_s == 3600


def test_caching_plan_kv_reuse_for_local(patched_registry, cache):
    """A provider declaring kv_cache_reuse yields kv_reuse."""
    patched_registry["ollama"] = _provider(
        "ollama",
        Capabilities(kv_cache_reuse=True, is_local=True),
    )
    plan = cache.caching_plan("ollama")
    assert plan.mode == "kv_reuse"
    assert plan.ttl_s is None


def test_caching_plan_none_when_unsupported(patched_registry, cache):
    """A provider with neither flag → none."""
    patched_registry["bare"] = _provider("bare", Capabilities())
    plan = cache.caching_plan("bare")
    assert plan.mode == "none"


def test_caching_plan_none_for_unknown_provider(patched_registry, cache):
    """A provider name not in the registry → none, no KeyError."""
    plan = cache.caching_plan("never_existed")
    assert plan.mode == "none"


# ---------------------------------------------------------------------------
# Size gate
# ---------------------------------------------------------------------------


def test_tiny_prefix_not_cached(tmp_path):
    """Below cache_min_prefix_tokens → record returns None and
    no entry persists; lookup also short-circuits to None."""
    cache = CrossSessionCache(
        index_path=tmp_path / "cache_index.json",
        cfg=_cfg(min_tokens=1024),  # ~4kB
    )
    entry = cache.record(
        workspace="/proj",
        prefix_text="tiny",
        provider="anthropic",
        provider_cache_id="srv-aaa",
        ttl_s=3600,
    )
    assert entry is None
    assert (
        cache.lookup(
            workspace="/proj",
            prefix_text="tiny",
            provider="anthropic",
        )
        is None
    )


def test_size_gate_off_when_min_tokens_zero(cache):
    """min_tokens=0 (test default) → any-size prefix caches."""
    entry = cache.record(
        workspace="/proj",
        prefix_text="x",  # 1 byte
        provider="anthropic",
        provider_cache_id="srv-aaa",
        ttl_s=3600,
    )
    assert entry is not None


# ---------------------------------------------------------------------------
# Persistence + clear
# ---------------------------------------------------------------------------


def test_record_persists_across_instances(tmp_path):
    """A record written in one CrossSessionCache instance must be
    visible to a fresh instance reading the same index file —
    that's the whole point of cross-session."""
    path = tmp_path / "ci.json"
    c1 = CrossSessionCache(index_path=path, cfg=_cfg())
    c1.record(
        workspace="/proj",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="srv-aaa",
        ttl_s=3600,
    )
    c2 = CrossSessionCache(index_path=path, cfg=_cfg())
    hit = c2.lookup(
        workspace="/proj",
        prefix_text="X" * 200,
        provider="anthropic",
    )
    assert hit is not None
    assert hit.provider_cache_id == "srv-aaa"


def test_cache_clear_empties_index(cache):
    cache.record(
        workspace="/proj",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="srv-aaa",
        ttl_s=3600,
    )
    cache.record(
        workspace="/proj2",
        prefix_text="Y" * 200,
        provider="openai",
        provider_cache_id="srv-bbb",
        ttl_s=3600,
    )
    n = cache.clear()
    assert n == 2
    assert cache.all() == []


def test_corrupted_index_file_starts_fresh(tmp_path):
    """A malformed JSON file doesn't crash construction — the
    cache silently starts empty (and the bad file will be
    overwritten on the next record)."""
    path = tmp_path / "ci.json"
    path.write_text("not valid json {{{", encoding="utf-8")
    c = CrossSessionCache(index_path=path, cfg=_cfg())
    assert c.all() == []


def test_all_returns_entries_sorted_desc(cache):
    cache.record(
        workspace="/a",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="s1",
        ttl_s=60,
    )
    time.sleep(0.01)
    cache.record(
        workspace="/b",
        prefix_text="Y" * 200,
        provider="openai",
        provider_cache_id="s2",
        ttl_s=60,
    )
    entries = cache.all()
    assert len(entries) == 2
    # Newer first
    assert entries[0].workspace == "/b"
    assert entries[1].workspace == "/a"
