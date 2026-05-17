"""In-process gateway registry — cross-subsystem lookup for the
running :class:`GatewayDaemon`."""
from __future__ import annotations

from types import SimpleNamespace

from athena.gateway import registry


def setup_function(_func) -> None:
    registry._clear_for_tests()


def _daemon_stub(profile: str = "default"):
    return SimpleNamespace(cfg=SimpleNamespace(profile=profile))


def test_register_and_get_roundtrip() -> None:
    d = _daemon_stub("p1")
    registry.register(d)
    assert registry.get("p1") is d


def test_get_returns_none_for_unknown_profile() -> None:
    assert registry.get("nope") is None


def test_register_two_profiles_isolated() -> None:
    a = _daemon_stub("p1")
    b = _daemon_stub("p2")
    registry.register(a)
    registry.register(b)
    assert registry.get("p1") is a
    assert registry.get("p2") is b


def test_unregister_only_removes_identity_match() -> None:
    """Re-creating a daemon for the same profile shouldn't have an
    earlier ``stop()`` wipe the successor's slot."""
    a = _daemon_stub("p1")
    b = _daemon_stub("p1")  # replacement; same profile
    registry.register(a)
    registry.register(b)  # overrides a (with a warning)
    # Stopping a now must NOT clear b's slot.
    registry.unregister(a)
    assert registry.get("p1") is b


def test_unregister_removes_self() -> None:
    a = _daemon_stub("p1")
    registry.register(a)
    registry.unregister(a)
    assert registry.get("p1") is None


def test_list_active_snapshot() -> None:
    a = _daemon_stub("p1")
    b = _daemon_stub("p2")
    registry.register(a)
    registry.register(b)
    active = registry.list_active()
    assert len(active) == 2
    assert a in active and b in active


def test_empty_profile_defaults_to_default() -> None:
    d = _daemon_stub("")
    registry.register(d)
    assert registry.get("default") is d
