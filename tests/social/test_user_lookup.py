"""Tests for lookup_x_user tool + SocialProvider.user_lookup / user_timeline.

Pins:
  - user_lookup resolves username → user profile dict
  - user_timeline fetches posts by user ID, normalised
  - user_timeline paginates across multiple pages
  - lookup_x_user chains lookup → timeline into one payload
  - next_token surfaces when more pages are available
  - missing user → available=false with clear reason
  - no token → graceful empty / None
  - bearer token used, OAuth never touched (same as search_x)
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from athena.providers.social import SocialProvider


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(
        social_bearer_token_path=None,
        social_search_url="https://example.test/search",
        social_search_query_param="query",
        social_search_extra_params={},
        social_post_url_template="https://x.com/{author}/status/{id}",
        social_user_lookup_url="https://api.x.com/2/users/by/username",
        social_user_timeline_url="https://api.x.com/2/users",
        social_user_timeline_max_results=50,
        social_user_timeline_extra_params={},
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _BearerCfg:
    """Cfg with a bearer token file pointing at a tmp_path file."""

    def __init__(self, tmp_path):
        self._path = tmp_path / "bearer.txt"
        self._path.write_text("TEST-BEARER-TOKEN", encoding="utf-8")
        self._ns = _cfg(social_bearer_token_path=str(self._path))

    def __getattr__(self, name):
        return getattr(self._ns, name)


class _OAuthForbidden:
    def access_token(self):
        raise AssertionError("OAuth must NOT be consulted when bearer present")

    def has_valid_token(self):
        raise AssertionError("OAuth must NOT be consulted when bearer present")


# ---------------------------------------------------------------
# SocialProvider.user_lookup
# ---------------------------------------------------------------


def test_user_lookup_returns_profile(tmp_path):
    cfg = _BearerCfg(tmp_path)
    seen_urls: list[str] = []

    def _transport(url: str, access_token: str) -> dict:
        seen_urls.append(url)
        return {
            "data": {
                "id": "12345",
                "username": "testuser",
                "name": "Test User",
                "description": "A test bio",
                "created_at": "2020-01-01T00:00:00Z",
                "public_metrics": {
                    "followers_count": 100,
                    "following_count": 50,
                    "tweet_count": 999,
                },
            }
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    result = sp.user_lookup("testuser")

    assert result is not None
    assert result["id"] == "12345"
    assert result["username"] == "testuser"
    assert result["description"] == "A test bio"
    assert len(seen_urls) == 1
    assert "testuser" in seen_urls[0]


def test_user_lookup_strips_at_prefix(tmp_path):
    cfg = _BearerCfg(tmp_path)
    seen_urls: list[str] = []

    def _transport(url: str, access_token: str) -> dict:
        seen_urls.append(url)
        return {"data": {"id": "1", "username": "someone"}}

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    sp.user_lookup("@someone")

    assert "someone" in seen_urls[0]
    assert "%40" not in seen_urls[0]


def test_user_lookup_empty_username():
    cfg = _cfg()
    sp = SocialProvider(cfg=cfg)
    assert sp.user_lookup("") is None
    assert sp.user_lookup("  ") is None
    assert sp.user_lookup("@") is None


def test_user_lookup_no_url_configured(tmp_path):
    cfg = _BearerCfg(tmp_path)
    cfg._ns.social_user_lookup_url = None

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden())
    assert sp.user_lookup("someone") is None


def test_user_lookup_user_not_found(tmp_path):
    cfg = _BearerCfg(tmp_path)

    def _transport(url: str, access_token: str) -> dict:
        return {"errors": [{"detail": "Could not find user"}]}

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    assert sp.user_lookup("nonexistent") is None


def test_user_lookup_no_token(tmp_path):
    cfg = _cfg(social_bearer_token_path=str(tmp_path / "missing.txt"))

    class _OAuthRaises:
        def access_token(self):
            raise RuntimeError("no token")

    sp = SocialProvider(cfg=cfg, oauth=_OAuthRaises())
    assert sp.user_lookup("someone") is None


# ---------------------------------------------------------------
# SocialProvider.user_timeline
# ---------------------------------------------------------------


def test_user_timeline_returns_normalised_posts(tmp_path):
    cfg = _BearerCfg(tmp_path)
    seen_urls: list[str] = []

    def _transport(url: str, access_token: str) -> dict:
        seen_urls.append(url)
        return {
            "data": [
                {
                    "id": "100",
                    "text": "first post",
                    "author_id": "12345",
                    "created_at": "2026-05-20T10:00:00Z",
                    "public_metrics": {"like_count": 10, "retweet_count": 2},
                },
                {
                    "id": "101",
                    "text": "second post",
                    "author_id": "12345",
                    "created_at": "2026-05-21T12:00:00Z",
                    "public_metrics": {"like_count": 25, "retweet_count": 5},
                },
            ],
            "includes": {"users": [{"id": "12345", "username": "testuser"}]},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    posts, next_token = sp.user_timeline("12345", max_results=10)

    assert len(posts) == 2
    assert posts[0]["text"] == "first post"
    assert posts[0]["author"] == "testuser"
    assert posts[0]["url"] == "https://x.com/testuser/status/100"
    assert posts[1]["text"] == "second post"
    assert posts[1]["metrics"]["like_count"] == 25
    assert "12345/tweets" in seen_urls[0]
    assert next_token is None


def test_user_timeline_empty_user_id():
    cfg = _cfg()
    sp = SocialProvider(cfg=cfg)
    posts, tok = sp.user_timeline("")
    assert posts == []
    assert tok is None
    posts2, tok2 = sp.user_timeline("  ")
    assert posts2 == []


def test_user_timeline_no_url_configured(tmp_path):
    cfg = _BearerCfg(tmp_path)
    cfg._ns.social_user_timeline_url = None

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden())
    posts, tok = sp.user_timeline("12345")
    assert posts == []
    assert tok is None


def test_user_timeline_no_token(tmp_path):
    cfg = _cfg(social_bearer_token_path=str(tmp_path / "missing.txt"))

    class _OAuthRaises:
        def access_token(self):
            raise RuntimeError("no token")

    sp = SocialProvider(cfg=cfg, oauth=_OAuthRaises())
    posts, tok = sp.user_timeline("12345")
    assert posts == []


def test_user_timeline_uses_bearer_not_oauth(tmp_path):
    cfg = _BearerCfg(tmp_path)
    seen_tokens: list[str] = []

    def _transport(url: str, access_token: str) -> dict:
        seen_tokens.append(access_token)
        return {"data": [], "meta": {}}

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    sp.user_timeline("12345")
    assert seen_tokens == ["TEST-BEARER-TOKEN"]


def test_user_timeline_respects_max_results(tmp_path):
    cfg = _BearerCfg(tmp_path)

    def _transport(url: str, access_token: str) -> dict:
        return {
            "data": [
                {
                    "id": str(i),
                    "text": f"post {i}",
                    "author_id": "1",
                    "created_at": "2026-01-01T00:00:00Z",
                }
                for i in range(20)
            ],
            "includes": {"users": [{"id": "1", "username": "u"}]},
            "meta": {},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    posts, _ = sp.user_timeline("1", max_results=5)
    assert len(posts) == 5


# ---------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------


def test_user_timeline_paginates_multiple_pages(tmp_path):
    """max_pages=3 fetches 3 pages, each with a next_token except the last."""
    cfg = _BearerCfg(tmp_path)
    call_count = 0

    def _transport(url: str, access_token: str) -> dict:
        nonlocal call_count
        call_count += 1
        page_id = call_count
        has_more = page_id < 3
        return {
            "data": [
                {
                    "id": f"{page_id}00",
                    "text": f"page {page_id} post",
                    "author_id": "1",
                    "created_at": f"2026-01-0{page_id}T00:00:00Z",
                }
            ],
            "includes": {"users": [{"id": "1", "username": "u"}]},
            "meta": {"next_token": f"tok-{page_id + 1}"} if has_more else {"meta": {}},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    posts, next_token = sp.user_timeline("1", max_results=100, max_pages=3)

    assert call_count == 3
    assert len(posts) == 3
    assert posts[0]["text"] == "page 1 post"
    assert posts[2]["text"] == "page 3 post"
    assert next_token is None


def test_user_timeline_returns_next_token_when_more_available(tmp_path):
    """max_pages=1 stops after first page and returns the next_token."""
    cfg = _BearerCfg(tmp_path)

    def _transport(url: str, access_token: str) -> dict:
        return {
            "data": [
                {"id": "1", "text": "post", "author_id": "1", "created_at": "2026-01-01T00:00:00Z"}
            ],
            "includes": {"users": [{"id": "1", "username": "u"}]},
            "meta": {"next_token": "continue-here"},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    posts, next_token = sp.user_timeline("1", max_pages=1)

    assert len(posts) == 1
    assert next_token == "continue-here"


def test_user_timeline_passes_pagination_token(tmp_path):
    """A provided pagination_token is sent in the URL params."""
    cfg = _BearerCfg(tmp_path)
    seen_urls: list[str] = []

    def _transport(url: str, access_token: str) -> dict:
        seen_urls.append(url)
        return {"data": [], "meta": {}}

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    sp.user_timeline("1", pagination_token="abc123")

    assert "pagination_token=abc123" in seen_urls[0]


def test_user_timeline_stops_when_total_reached(tmp_path):
    """Stops paginating once max_results total posts are collected."""
    cfg = _BearerCfg(tmp_path)
    call_count = 0

    def _transport(url: str, access_token: str) -> dict:
        nonlocal call_count
        call_count += 1
        return {
            "data": [
                {
                    "id": str(i),
                    "text": f"p{i}",
                    "author_id": "1",
                    "created_at": "2026-01-01T00:00:00Z",
                }
                for i in range(3)
            ],
            "includes": {"users": [{"id": "1", "username": "u"}]},
            "meta": {"next_token": "more"},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    posts, _ = sp.user_timeline("1", max_results=5, max_pages=10)

    assert len(posts) == 5
    assert call_count == 2


# ---------------------------------------------------------------
# lookup_x_user tool (end-to-end through the tool function)
# ---------------------------------------------------------------


def test_lookup_x_user_tool_payload_shape(tmp_path, monkeypatch):
    """The tool returns the expected JSON shape with profile + posts."""
    cfg = _BearerCfg(tmp_path)
    call_log: list[tuple[str, str]] = []

    def _transport(url: str, access_token: str) -> dict:
        call_log.append(("GET", url))
        if "by/username" in url:
            return {
                "data": {
                    "id": "42",
                    "username": "knubeltierli",
                    "name": "Knubeltierli",
                    "description": "Test bio",
                    "public_metrics": {"followers_count": 10},
                }
            }
        if "/tweets" in url:
            return {
                "data": [
                    {
                        "id": "900",
                        "text": "hello world",
                        "author_id": "42",
                        "created_at": "2026-05-20T00:00:00Z",
                    }
                ],
                "includes": {"users": [{"id": "42", "username": "knubeltierli"}]},
                "meta": {},
            }
        return {}

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)

    monkeypatch.setattr(
        "athena.social.user_lookup._resolve_social_provider",
        lambda: ("social", sp),
    )

    from athena.social.user_lookup import lookup_x_user

    result = json.loads(lookup_x_user(username="knubeltierli"))

    assert result["available"] is True
    assert result["profile"]["username"] == "knubeltierli"
    assert result["profile"]["description"] == "Test bio"
    assert len(result["posts"]) == 1
    assert result["posts"][0]["text"] == "hello world"
    assert len(call_log) == 2


def test_lookup_x_user_with_pagination(tmp_path, monkeypatch):
    """max_pages flows through to user_timeline and next_token surfaces."""
    cfg = _BearerCfg(tmp_path)
    page_calls = 0

    def _transport(url: str, access_token: str) -> dict:
        nonlocal page_calls
        if "by/username" in url:
            return {"data": {"id": "42", "username": "u"}}
        page_calls += 1
        has_more = page_calls < 2
        return {
            "data": [
                {
                    "id": f"{page_calls}0",
                    "text": f"page {page_calls}",
                    "author_id": "42",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
            "includes": {"users": [{"id": "42", "username": "u"}]},
            "meta": {"next_token": "next"} if has_more else {},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    monkeypatch.setattr(
        "athena.social.user_lookup._resolve_social_provider",
        lambda: ("social", sp),
    )

    from athena.social.user_lookup import lookup_x_user

    result = json.loads(lookup_x_user(username="u", max_pages=3))
    assert result["available"] is True
    assert len(result["posts"]) == 2
    assert "next_token" not in result


def test_lookup_x_user_surfaces_next_token(tmp_path, monkeypatch):
    """When max_pages=1 and more pages exist, next_token is in the payload."""
    cfg = _BearerCfg(tmp_path)

    def _transport(url: str, access_token: str) -> dict:
        if "by/username" in url:
            return {"data": {"id": "1", "username": "u"}}
        return {
            "data": [
                {"id": "1", "text": "p", "author_id": "1", "created_at": "2026-01-01T00:00:00Z"}
            ],
            "includes": {"users": [{"id": "1", "username": "u"}]},
            "meta": {"next_token": "resume-here"},
        }

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    monkeypatch.setattr(
        "athena.social.user_lookup._resolve_social_provider",
        lambda: ("social", sp),
    )

    from athena.social.user_lookup import lookup_x_user

    result = json.loads(lookup_x_user(username="u", max_pages=1))
    assert result["next_token"] == "resume-here"


def test_lookup_x_user_user_not_found(tmp_path, monkeypatch):
    cfg = _BearerCfg(tmp_path)

    def _transport(url: str, access_token: str) -> dict:
        return {"errors": [{"detail": "not found"}]}

    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden(), transport=_transport)
    monkeypatch.setattr(
        "athena.social.user_lookup._resolve_social_provider",
        lambda: ("social", sp),
    )

    from athena.social.user_lookup import lookup_x_user

    result = json.loads(lookup_x_user(username="ghost"))
    assert result["available"] is False
    assert "not found" in result["reason"]


def test_lookup_x_user_empty_username():
    from athena.social.user_lookup import lookup_x_user

    result = json.loads(lookup_x_user(username=""))
    assert result["available"] is False
    assert "empty" in result["reason"]


def test_lookup_x_user_no_provider(monkeypatch):
    monkeypatch.setattr(
        "athena.social.user_lookup._resolve_social_provider",
        lambda: (None, None),
    )

    from athena.social.user_lookup import lookup_x_user

    result = json.loads(lookup_x_user(username="someone"))
    assert result["available"] is False
    assert "no social-search provider" in result["reason"]


def test_lookup_x_user_surfaces_timeline_http_error(tmp_path, monkeypatch):
    """A profile that loads but whose timeline call is rejected by X
    (402/403/429) must surface the real HTTP reason, not masquerade as a
    genuinely post-less account. Exercises the production urllib path so
    SocialProvider.last_error is set the way it is against the live API.
    """
    import io
    import urllib.error

    cfg = _BearerCfg(tmp_path)

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self._body

    def _fake_urlopen(req, timeout=20):
        url = req.full_url
        if "by/username" in url:
            body = json.dumps({"data": {"id": "42", "username": "vv"}}).encode()
            return _FakeResp(body)
        if "/tweets" in url:
            raise urllib.error.HTTPError(
                url,
                429,
                "Too Many Requests",
                None,
                io.BytesIO(b'{"title":"Too Many Requests","status":429}'),
            )
        return _FakeResp(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    # No transport injected → _get takes the real urllib branch.
    sp = SocialProvider(cfg=cfg, oauth=_OAuthForbidden())
    monkeypatch.setattr(
        "athena.social.user_lookup._resolve_social_provider",
        lambda: ("social", sp),
    )

    from athena.social.user_lookup import lookup_x_user

    result = json.loads(lookup_x_user(username="vv"))

    assert result["available"] is True
    assert result["profile"]["username"] == "vv"
    assert result["posts"] == []
    assert result["reason"] is not None
    assert "429" in result["reason"]
