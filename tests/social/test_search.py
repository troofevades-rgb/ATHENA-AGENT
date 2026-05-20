"""Tests for the social provider + search_x tool (T6-02.3).

The provider's social_search is exercised against a stubbed HTTP
transport. The search_x tool is exercised against a stubbed
provider resolution + provider instance, so the routing + visible-
switch contract is pinned without any real network or OAuth.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.providers.social import SocialProvider
from athena.social import search as search_module


# ---------------------------------------------------------------------------
# Capability + routing
# ---------------------------------------------------------------------------


def test_capability_declares_social_search():
    """The provider's static_capabilities declares
    social_search=True — the lookup the broker performs."""
    caps = SocialProvider.static_capabilities()
    assert caps.social_search is True
    assert caps.supports("social_search") is True


def test_routing_picks_social_provider():
    """best_provider_for({'social_search'}) finds the social
    provider in the live registry (registered at import time)."""
    from athena.providers import best_provider_for

    name = best_provider_for({"social_search"})
    assert name == "social"


def test_routing_none_when_no_provider_declares(monkeypatch):
    """With an empty registry → no name returned. The
    search_x tool then surfaces 'not configured' cleanly."""
    monkeypatch.setattr("athena.providers._REGISTRY", {})
    from athena.providers import best_provider_for

    assert best_provider_for({"social_search"}) is None


# ---------------------------------------------------------------------------
# social_search response normalisation
# ---------------------------------------------------------------------------


_VENDOR_SAMPLE = {
    "data": [
        {
            "id": "1",
            "text": "post about athena",
            "author_id": "u1",
            "created_at": "2026-05-19T10:00:00Z",
            "public_metrics": {"like_count": 42, "retweet_count": 3},
        },
        {
            "id": "2",
            "text": "another mention",
            "author_id": "u2",
            "created_at": "2026-05-19T11:00:00Z",
        },
    ],
    "includes": {
        "users": [
            {"id": "u1", "username": "alice"},
            {"id": "u2", "username": "bob"},
        ],
    },
}


def _stub_cfg(**overrides) -> SimpleNamespace:
    base = dict(
        social_search_url="https://example.test/v1/search",
        social_search_query_param="query",
        social_search_extra_params={},
        social_post_url_template="https://example.test/{author}/status/{id}",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_search_normalizes_results():
    """The vendor blob maps cleanly to the {author, text,
    timestamp, url, metrics?} shape."""
    calls: list[tuple[str, str]] = []

    def fake_transport(url: str, token: str) -> dict:
        calls.append((url, token))
        return dict(_VENDOR_SAMPLE)

    class _StubOAuth:
        def access_token(self) -> str:
            return "fake-token"

        def has_valid_token(self) -> bool:
            return True

    provider = SocialProvider(
        oauth=_StubOAuth(),
        transport=fake_transport,
        cfg=_stub_cfg(),
    )

    results = provider.social_search("athena", max_results=10)
    assert len(results) == 2
    first = results[0]
    assert first["author"] == "alice"
    assert first["text"] == "post about athena"
    assert first["timestamp"] == "2026-05-19T10:00:00Z"
    assert first["url"] == "https://example.test/alice/status/1"
    assert first["metrics"] == {"like_count": 42, "retweet_count": 3}
    # The transport was called with the bearer token + the
    # constructed query URL.
    assert calls[0][0].startswith("https://example.test/v1/search?")
    assert "query=athena" in calls[0][0]
    assert calls[0][1] == "fake-token"


def test_search_empty_query_returns_empty():
    provider = SocialProvider(
        oauth=SimpleNamespace(access_token=lambda: "t", has_valid_token=lambda: True),
        transport=lambda url, token: {"data": []},
        cfg=_stub_cfg(),
    )
    assert provider.social_search("   ", max_results=10) == []


def test_search_no_token_returns_empty():
    """OAuth.access_token raises → search returns [] with a log
    rather than blowing up the agent turn."""

    class _NoToken:
        def access_token(self) -> str:
            raise RuntimeError("no token")

        def has_valid_token(self) -> bool:
            return False

    provider = SocialProvider(
        oauth=_NoToken(),
        transport=lambda url, token: {"data": []},
        cfg=_stub_cfg(),
    )
    assert provider.social_search("anything") == []


def test_search_no_url_configured_returns_empty():
    """Missing social_search_url → degrades to empty + a log."""
    provider = SocialProvider(
        oauth=SimpleNamespace(access_token=lambda: "t", has_valid_token=lambda: True),
        transport=lambda url, token: {"data": []},
        cfg=_stub_cfg(social_search_url=None),
    )
    assert provider.social_search("anything") == []


def test_search_transport_failure_returns_empty():
    """Transport returns None → empty result, no crash."""
    provider = SocialProvider(
        oauth=SimpleNamespace(access_token=lambda: "t", has_valid_token=lambda: True),
        transport=lambda url, token: None,
        cfg=_stub_cfg(),
    )
    assert provider.social_search("query") == []


# ---------------------------------------------------------------------------
# search_x tool — visible switch + degraded path
# ---------------------------------------------------------------------------


class _StubProvider:
    def __init__(self, *, results: list[dict] | None = None, available: bool = True):
        self._results = results or []
        self._available = available
        self.calls: list[tuple[str, int]] = []

    def is_available(self) -> bool:
        return self._available

    def social_search(self, query: str, *, max_results: int) -> list[dict]:
        self.calls.append((query, max_results))
        return list(self._results)


def test_visible_switch_surfaced(monkeypatch, capsys):
    """A successful search prints "searching X via <provider>"
    via ui.info — the user / operator sees which backend ran the
    search."""
    stub_provider = _StubProvider(
        results=[
            {
                "author": "alice",
                "text": "hello",
                "timestamp": "now",
                "url": "https://example.test/1",
            }
        ]
    )
    monkeypatch.setattr(
        search_module,
        "_resolve_social_provider",
        lambda: ("social", stub_provider),
    )

    out = search_module.search_x(query="topic", max_results=5)
    captured = capsys.readouterr().out
    # The visible switch — ui.info routes through stdout in
    # athena's UI.
    assert "searching X via social" in captured or "searching X via social" in capsys.readouterr().out

    payload = json.loads(out)
    assert payload["available"] is True
    assert payload["provider"] == "social"
    assert len(payload["results"]) == 1
    assert payload["results"][0]["author"] == "alice"
    assert stub_provider.calls == [("topic", 5)]


def test_search_x_no_provider_degrades_cleanly(monkeypatch, capsys):
    """No social provider declared → tool returns
    available=false with a clear reason — never raises into the
    agent loop."""
    monkeypatch.setattr(
        search_module, "_resolve_social_provider", lambda: (None, None)
    )

    out = search_module.search_x(query="anything")
    payload = json.loads(out)
    assert payload["available"] is False
    assert "no social-search provider" in (payload["reason"] or "")
    assert payload["results"] == []


def test_search_x_provider_declared_but_not_available(monkeypatch):
    """The resolver hands back (name, None) when a provider
    declares the capability but isn't ready (e.g. no OAuth
    token) — the tool surfaces that as the same not-ready
    error."""
    monkeypatch.setattr(
        search_module, "_resolve_social_provider", lambda: ("social", None)
    )
    out = search_module.search_x(query="anything")
    payload = json.loads(out)
    assert payload["available"] is False


def test_search_x_provider_raises_returns_structured_error(monkeypatch):
    """A provider exception → structured error payload, never
    propagates."""

    class _Boom:
        def is_available(self):
            return True

        def social_search(self, q, *, max_results):
            raise RuntimeError("vendor exploded")

    monkeypatch.setattr(
        search_module, "_resolve_social_provider", lambda: ("social", _Boom())
    )
    out = search_module.search_x(query="x")
    payload = json.loads(out)
    assert payload["available"] is False
    assert "vendor exploded" in (payload["reason"] or "")
    assert payload["provider"] == "social"


def test_search_x_empty_query():
    out = search_module.search_x(query="   ")
    payload = json.loads(out)
    assert payload["available"] is False
    assert payload["reason"] == "empty query"


def test_search_x_uses_cfg_default_max_results(monkeypatch):
    stub_provider = _StubProvider(results=[])
    monkeypatch.setattr(
        search_module, "_resolve_social_provider", lambda: ("social", stub_provider)
    )
    monkeypatch.setattr(
        "athena.config.load_config",
        lambda: SimpleNamespace(social_search_max_results=42),
    )
    search_module.search_x(query="x")
    assert stub_provider.calls == [("x", 42)]
