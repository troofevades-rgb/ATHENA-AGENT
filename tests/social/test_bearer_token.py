"""Bearer-token-only auth path tests.

X / Twitter v2 (and several other social vendors) issue an
app-only Bearer token out of their developer portal. This is
the simplest auth model — single string, no OAuth flow. The
SocialProvider prefers it when configured; OAuth falls back
when not.

Pins:
  - bearer token loaded from a 0o600 file
  - is_available True when bearer-token-only configured
  - social_search uses Bearer auth without touching OAuth
  - bearer takes priority over OAuth when both present
  - missing file / empty file / unreadable file → None
  - the token NEVER appears in logs
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.providers.social import (
    SocialProvider,
    _read_bearer_token,
)


# ---------------------------------------------------------------
# _read_bearer_token — module-level helper
# ---------------------------------------------------------------


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(
        social_bearer_token_path=None,
        social_search_url="https://example.test/search",
        social_search_query_param="query",
        social_search_extra_params={},
        social_post_url_template="",
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_read_bearer_token_returns_none_when_unset():
    assert _read_bearer_token(_cfg()) is None


def test_read_bearer_token_returns_none_when_path_missing(tmp_path: Path):
    cfg = _cfg(social_bearer_token_path=str(tmp_path / "nope.txt"))
    assert _read_bearer_token(cfg) is None


def test_read_bearer_token_strips_whitespace(tmp_path: Path):
    p = tmp_path / "bearer.txt"
    p.write_text("  TOKEN-VALUE\n\n", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path=str(p))
    assert _read_bearer_token(cfg) == "TOKEN-VALUE"


def test_read_bearer_token_empty_file_returns_none(tmp_path: Path):
    p = tmp_path / "empty.txt"
    p.write_text("\n\n   \n", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path=str(p))
    assert _read_bearer_token(cfg) is None


def test_read_bearer_token_handles_tilde_expansion(tmp_path: Path, monkeypatch):
    """A leading ~ in the cfg should resolve to the home dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    p = tmp_path / "bearer.txt"
    p.write_text("TKN", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path="~/bearer.txt")
    assert _read_bearer_token(cfg) == "TKN"


def test_read_bearer_token_never_logs_token(tmp_path: Path, caplog):
    """The token must NOT appear anywhere in the log output —
    the helper logs only the path + the length."""
    p = tmp_path / "bearer.txt"
    p.write_text("VERY-SECRET-TOKEN-AABBCC", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path=str(p))
    caplog.set_level(logging.DEBUG, logger="athena.providers.social")
    assert _read_bearer_token(cfg) == "VERY-SECRET-TOKEN-AABBCC"
    # The full DEBUG capture should mention the length but never
    # the token itself.
    assert "VERY-SECRET-TOKEN-AABBCC" not in caplog.text
    assert "len=24" in caplog.text


# ---------------------------------------------------------------
# SocialProvider — is_available with bearer-token-only
# ---------------------------------------------------------------


def test_is_available_true_when_bearer_token_present(tmp_path: Path):
    p = tmp_path / "bearer.txt"
    p.write_text("TOKEN", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path=str(p))
    sp = SocialProvider(cfg=cfg)
    assert sp.is_available() is True


def test_is_available_false_when_neither_bearer_nor_oauth(tmp_path: Path):
    """No bearer file + no OAuth token → False. The provider is
    'declared but not configured' and search_x surfaces a clean
    'no provider' message."""
    cfg = _cfg(social_bearer_token_path=str(tmp_path / "missing.txt"))
    sp = SocialProvider(cfg=cfg)
    # Stub the OAuth side to return False so the test doesn't
    # depend on a real on-disk OAuth token.
    class _NoOAuth:
        def has_valid_token(self):
            return False
    sp._oauth = _NoOAuth()
    assert sp.is_available() is False


def test_is_available_falls_back_to_oauth_when_no_bearer():
    cfg = _cfg(social_bearer_token_path=None)
    sp = SocialProvider(cfg=cfg)
    class _OAuth:
        def has_valid_token(self):
            return True
    sp._oauth = _OAuth()
    assert sp.is_available() is True


# ---------------------------------------------------------------
# social_search — bearer-token path
# ---------------------------------------------------------------


def test_social_search_uses_bearer_without_touching_oauth(tmp_path: Path):
    """When the bearer token is configured, the OAuth adapter
    is NEVER consulted — pinned by an OAuth stub that raises
    if anyone calls .access_token()."""
    p = tmp_path / "bearer.txt"
    p.write_text("BEARER-TOK-AB12", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path=str(p))

    class _OAuthForbidden:
        def access_token(self):
            raise AssertionError("OAuth must NOT be consulted when bearer present")
        def has_valid_token(self):
            raise AssertionError("OAuth must NOT be consulted when bearer present")

    seen_authorization: list[str | None] = []

    def _transport(url: str, access_token: str) -> dict:
        seen_authorization.append(access_token)
        return {
            "data": [
                {
                    "id": "1",
                    "text": "hello world",
                    "author_id": "10",
                    "created_at": "2026-01-01T00:00:00Z",
                    "public_metrics": {"like_count": 5},
                },
            ],
            "includes": {"users": [{"id": "10", "username": "athena_test"}]},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    out = sp.social_search("test query", max_results=5)

    # Bearer was used.
    assert seen_authorization == ["BEARER-TOK-AB12"]
    # Result is normalised properly.
    assert len(out) == 1
    assert out[0]["author"] == "athena_test"
    assert out[0]["text"] == "hello world"
    assert out[0]["metrics"]["like_count"] == 5


def test_social_search_oauth_fallback_when_no_bearer():
    """No bearer-token path → OAuth provides the token. Confirms
    the existing OAuth path still works after the refactor."""
    cfg = _cfg(social_bearer_token_path=None)

    class _OAuth:
        def access_token(self):
            return "OAUTH-TOK"
        def has_valid_token(self):
            return True

    seen: list[str] = []

    def _transport(url: str, access_token: str) -> dict:
        seen.append(access_token)
        return {"data": []}

    sp = SocialProvider(cfg=cfg, oauth=_OAuth(), transport=_transport)
    sp.social_search("query", max_results=5)
    assert seen == ["OAUTH-TOK"]


def test_social_search_no_token_returns_empty(tmp_path: Path):
    """Neither bearer nor OAuth available → empty list (graceful
    degradation; search_x surfaces 'no provider configured')."""
    cfg = _cfg(social_bearer_token_path=str(tmp_path / "missing.txt"))

    class _OAuthRaises:
        def access_token(self):
            raise RuntimeError("no token on disk")

    transport_calls: list = []

    def _transport(url: str, access_token: str) -> dict:
        transport_calls.append((url, access_token))
        return {"data": []}

    sp = SocialProvider(cfg=cfg, oauth=_OAuthRaises(), transport=_transport)
    out = sp.social_search("query")
    assert out == []
    # The transport was NEVER reached — the empty token short-
    # circuits before any network call.
    assert transport_calls == []


def test_bearer_token_never_in_logs(tmp_path: Path, caplog):
    """The end-to-end search path: bearer in file, search runs,
    full DEBUG log captured. The token MUST NOT appear anywhere
    in the captured text — this is the load-bearing leak guard."""
    p = tmp_path / "bearer.txt"
    p.write_text("TOKEN-MUST-NEVER-LEAK-ZZ9", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path=str(p))

    def _transport(url: str, access_token: str) -> dict:
        return {"data": []}

    sp = SocialProvider(cfg=cfg, transport=_transport)
    caplog.set_level(logging.DEBUG, logger="athena.providers.social")
    sp.social_search("query")
    assert "TOKEN-MUST-NEVER-LEAK-ZZ9" not in caplog.text


# ---------------------------------------------------------------
# Priority: bearer takes priority over OAuth
# ---------------------------------------------------------------


def test_bearer_takes_priority_over_oauth(tmp_path: Path):
    """Both configured → bearer wins. OAuth never consulted."""
    p = tmp_path / "bearer.txt"
    p.write_text("BEARER-PRI", encoding="utf-8")
    cfg = _cfg(social_bearer_token_path=str(p))

    class _OAuth:
        def __init__(self):
            self.calls = 0
        def access_token(self):
            self.calls += 1
            return "OAUTH-FALLBACK"
        def has_valid_token(self):
            self.calls += 1
            return True

    oauth = _OAuth()
    seen: list[str] = []

    def _transport(url: str, access_token: str) -> dict:
        seen.append(access_token)
        return {"data": []}

    sp = SocialProvider(cfg=cfg, oauth=oauth, transport=_transport)
    sp.social_search("query")
    assert seen == ["BEARER-PRI"]
    assert oauth.calls == 0
