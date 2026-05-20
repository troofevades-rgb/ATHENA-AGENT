"""Tests for the capability-manifest-driven MediaRegistry (T5-05.1).

The registry returns provider classes (not instances) — class-level
lookup over the T5-01 manifest with the local-first tie-break.
Tests stub the module-level _REGISTRY with synthetic provider
classes so they don't depend on the live provider set.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from athena.media.registry import MediaRegistry
from athena.providers.base import Capabilities, Provider


# ---------------------------------------------------------------------------
# Synthetic provider classes
# ---------------------------------------------------------------------------


def _make_provider(name: str, caps: Capabilities) -> type[Provider]:
    """Build a Provider subclass with the given static capabilities.
    The class never runs — we only need its static_capabilities()
    + .name for registry-level routing."""

    class _Stub(Provider):
        pass

    _Stub.name = name
    _Stub.static_capabilities = classmethod(lambda cls, model=None: caps)  # type: ignore[method-assign]
    # ABC won't let us instantiate without implementations, but the
    # registry never instantiates — it just inspects the class.
    return _Stub


@pytest.fixture
def patched_registry(monkeypatch):
    """Replace athena.providers._REGISTRY (and the media.registry
    module-level reference) with a deterministic set."""
    new_registry: dict[str, type[Provider]] = {}
    monkeypatch.setattr("athena.providers._REGISTRY", new_registry)
    monkeypatch.setattr("athena.media.registry._REGISTRY", new_registry)
    return new_registry


# ---------------------------------------------------------------------------
# backend_for
# ---------------------------------------------------------------------------


def test_backend_for_returns_none_when_no_capability(patched_registry):
    """No provider declares vision → backend_for returns None."""
    patched_registry["nv1"] = _make_provider("nv1", Capabilities(vision=False))
    patched_registry["nv2"] = _make_provider("nv2", Capabilities(vision=False))

    mr = MediaRegistry(cfg=SimpleNamespace(media_backend_prefer="local"))
    assert mr.backend_for("vision") is None


def test_backend_for_prefers_local(patched_registry):
    """When multiple providers declare a capability and one is
    local, local wins under the default preference."""
    patched_registry["hosted"] = _make_provider(
        "hosted", Capabilities(vision=True, is_local=False)
    )
    patched_registry["onsite"] = _make_provider(
        "onsite", Capabilities(vision=True, is_local=True)
    )
    patched_registry["alt"] = _make_provider(
        "alt", Capabilities(vision=True, is_local=False)
    )

    mr = MediaRegistry(cfg=SimpleNamespace(media_backend_prefer="local"))
    result = mr.backend_for("vision")
    assert result is not None
    assert result.name == "onsite"


def test_backend_for_falls_back_to_first_when_no_local(patched_registry):
    """No local backend → return the alphabetically-first
    declared provider for determinism."""
    patched_registry["zeta"] = _make_provider(
        "zeta", Capabilities(vision=True, is_local=False)
    )
    patched_registry["alpha"] = _make_provider(
        "alpha", Capabilities(vision=True, is_local=False)
    )

    mr = MediaRegistry(cfg=SimpleNamespace(media_backend_prefer="local"))
    result = mr.backend_for("vision")
    assert result is not None
    assert result.name == "alpha"  # alphabetical


def test_backend_for_ignores_local_under_any(patched_registry):
    """media_backend_prefer='any' → first alphabetical wins
    regardless of locality."""
    patched_registry["zlocal"] = _make_provider(
        "zlocal", Capabilities(vision=True, is_local=True)
    )
    patched_registry["ahosted"] = _make_provider(
        "ahosted", Capabilities(vision=True, is_local=False)
    )

    mr = MediaRegistry(cfg=SimpleNamespace(media_backend_prefer="any"))
    result = mr.backend_for("vision")
    assert result is not None
    assert result.name == "ahosted"


# ---------------------------------------------------------------------------
# Routing decision logging
# ---------------------------------------------------------------------------


def test_routing_decision_logged(patched_registry, caplog):
    patched_registry["onsite"] = _make_provider(
        "onsite", Capabilities(vision=True, is_local=True)
    )

    mr = MediaRegistry(cfg=SimpleNamespace(media_backend_prefer="local"))
    with caplog.at_level(logging.INFO, logger="athena.media.registry"):
        mr.backend_for("vision")
    assert any("media:vision" in r.message for r in caplog.records)
    assert any("onsite" in r.message for r in caplog.records)


def test_no_backend_decision_also_logged(patched_registry, caplog):
    """When backend_for returns None, the absence is logged at
    INFO too — operators want to know why a tool wasn't
    advertised."""
    mr = MediaRegistry(cfg=SimpleNamespace(media_backend_prefer="local"))
    with caplog.at_level(logging.INFO, logger="athena.media.registry"):
        result = mr.backend_for("video_generation")
    assert result is None
    assert any("video_generation" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# candidates / can
# ---------------------------------------------------------------------------


def test_candidates_returns_sorted_names(patched_registry):
    patched_registry["zeta"] = _make_provider("zeta", Capabilities(vision=True))
    patched_registry["alpha"] = _make_provider("alpha", Capabilities(vision=True))
    patched_registry["nv"] = _make_provider("nv", Capabilities(vision=False))

    mr = MediaRegistry(cfg=SimpleNamespace())
    assert mr.candidates("vision") == ["alpha", "zeta"]


def test_can_reflects_at_least_one_declaration(patched_registry):
    mr = MediaRegistry(cfg=SimpleNamespace())
    assert mr.can("vision") is False
    patched_registry["v"] = _make_provider("v", Capabilities(vision=True))
    assert mr.can("vision") is True
