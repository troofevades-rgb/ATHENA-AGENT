"""Tests for the social OAuth adapter (T6-02.2).

The token endpoint is stubbed via the transport constructor
parameter — no live network. The load-bearing properties:

  - tokens persist via athena.safety.secure_files (0o600)
  - refresh fires when the stored token is expired
  - token material never appears in logs (capture & assert
    redaction)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.social.oauth import (
    SocialOAuth,
    TokenResponse,
    TokenStore,
    _parse_token_response,
    _redact_for_log,
)


_DEFAULT_CFG = dict(
    social_oauth_authorize_url="https://example.test/oauth/authorize",
    social_oauth_token_url="https://example.test/oauth/token",
    social_oauth_client_id="client-id-abc",
    social_oauth_client_secret_path=None,
    social_oauth_scopes=["tweet.read", "users.read"],
    social_oauth_redirect_uri="http://localhost:9876/callback",
)


def _cfg(**overrides) -> SimpleNamespace:
    base = dict(_DEFAULT_CFG)
    base.update(overrides)
    return SimpleNamespace(**base)


class _StubTransport:
    """Records calls + returns a canned token response."""

    def __init__(
        self,
        *,
        status: int = 200,
        body: dict | None = None,
        responses: list[dict] | None = None,
    ):
        self.status = status
        self.body = body or {}
        self.responses = list(responses or [])
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, body: dict) -> TokenResponse:
        self.calls.append((url, dict(body)))
        if self.responses:
            payload = self.responses.pop(0)
            return TokenResponse(status=200, body=payload)
        return TokenResponse(status=self.status, body=dict(self.body))


# ---------------------------------------------------------------------------
# exchange() persists via secure_files
# ---------------------------------------------------------------------------


def test_exchange_stores_token_via_secrets(tmp_path: Path):
    """A successful exchange writes the token JSON at 0o600 via
    athena.safety.secure_files (so the file is created via O_EXCL
    + atomic-replace; mode never goes wider than 0o600)."""
    transport = _StubTransport(
        body={
            "access_token": "tok-xyz",
            "refresh_token": "ref-abc",
            "expires_in": 3600,
            "scope": "tweet.read",
            "token_type": "Bearer",
        }
    )
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=transport)
    tok = o.exchange("authcode")
    assert tok.access_token == "tok-xyz"
    assert tok.refresh_token == "ref-abc"
    assert tok.expires_at > time.time()
    # Persisted file exists
    persisted = tmp_path / "social_token.json"
    assert persisted.exists()
    # On Linux/macOS we can verify mode; on Windows it's a no-op
    # (file mode bits aren't enforced by ACLs the same way).
    import sys

    if sys.platform != "win32":
        import stat as _stat

        assert _stat.S_IMODE(persisted.stat().st_mode) == 0o600


def test_exchange_requires_code(tmp_path: Path):
    """Empty code → ValueError before transport hits."""
    transport = _StubTransport()
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=transport)
    with pytest.raises(ValueError):
        o.exchange("")
    assert transport.calls == []


# ---------------------------------------------------------------------------
# Refresh-on-expired
# ---------------------------------------------------------------------------


def test_refresh_on_expired(tmp_path: Path):
    """access_token() on a token past expiry triggers a refresh
    call against the token endpoint; the new access_token comes
    back to the caller."""
    transport = _StubTransport(
        body={
            "access_token": "new-tok",
            "refresh_token": "ref-abc",
            "expires_in": 3600,
            "scope": "tweet.read",
        }
    )
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=transport)
    # Plant an expired token directly on disk.
    expired = TokenStore(
        access_token="old-tok",
        refresh_token="ref-abc",
        expires_at=time.time() - 1000,
        scope="tweet.read",
    )
    from athena.safety.secure_files import secure_write_json

    secure_write_json(tmp_path / "social_token.json", expired.to_dict(), mode=0o600)
    o._cached = None  # force re-read from disk

    # access_token now refreshes via transport.
    new = o.access_token()
    assert new == "new-tok"
    # Transport saw a refresh_token grant_type body.
    assert any(
        call[1].get("grant_type") == "refresh_token" for call in transport.calls
    )


def test_refresh_failure_raises_runtime_error(tmp_path: Path):
    """Refresh that returns non-200 → RuntimeError, no silent
    fall-through. The caller should re-run authorize."""
    transport = _StubTransport(status=400)
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=transport)
    from athena.safety.secure_files import secure_write_json

    expired = TokenStore(
        access_token="old", refresh_token="ref-abc",
        expires_at=time.time() - 1000, scope="tweet.read",
    )
    secure_write_json(tmp_path / "social_token.json", expired.to_dict(), mode=0o600)
    with pytest.raises(RuntimeError):
        o.access_token()


def test_access_token_without_refresh_raises(tmp_path: Path):
    """Expired token + no refresh_token → RuntimeError telling
    the user to re-authorize."""
    transport = _StubTransport()
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=transport)
    from athena.safety.secure_files import secure_write_json

    expired = TokenStore(
        access_token="old", refresh_token=None,
        expires_at=time.time() - 1000, scope="tweet.read",
    )
    secure_write_json(tmp_path / "social_token.json", expired.to_dict(), mode=0o600)
    with pytest.raises(RuntimeError, match="re-run authorize"):
        o.access_token()
    # No transport call — there was no refresh_token to send.
    assert transport.calls == []


# ---------------------------------------------------------------------------
# has_valid_token
# ---------------------------------------------------------------------------


def test_has_valid_token_false_when_absent(tmp_path: Path):
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=_StubTransport())
    assert o.has_valid_token() is False


def test_has_valid_token_false_when_expired(tmp_path: Path):
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=_StubTransport())
    from athena.safety.secure_files import secure_write_json

    expired = TokenStore(
        access_token="old", refresh_token="ref",
        expires_at=time.time() - 100, scope="",
    )
    secure_write_json(tmp_path / "social_token.json", expired.to_dict(), mode=0o600)
    assert o.has_valid_token() is False


def test_has_valid_token_true_when_alive(tmp_path: Path):
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=_StubTransport())
    from athena.safety.secure_files import secure_write_json

    alive = TokenStore(
        access_token="tok",
        refresh_token="ref",
        expires_at=time.time() + 3600,
        scope="",
    )
    secure_write_json(tmp_path / "social_token.json", alive.to_dict(), mode=0o600)
    assert o.has_valid_token() is True


# ---------------------------------------------------------------------------
# Token never in logs (the load-bearing safety property)
# ---------------------------------------------------------------------------


def test_token_never_in_logs(tmp_path: Path, caplog):
    """Capture EVERY log emitted across a full exchange + access
    cycle and assert no access_token / refresh_token material
    leaks through."""
    transport = _StubTransport(
        body={
            "access_token": "VERY-SECRET-TOKEN-DO-NOT-LEAK",
            "refresh_token": "REFRESH-SECRET-NOPE",
            "expires_in": 3600,
            "scope": "tweet.read",
        }
    )
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=transport)
    with caplog.at_level(logging.DEBUG):
        tok = o.exchange("authcode")
        # And another op for good measure.
        _ = o.access_token()
        # And the repr / str of the TokenStore.
        repr(tok)
        str(tok)
    full_log = caplog.text
    assert "VERY-SECRET-TOKEN-DO-NOT-LEAK" not in full_log
    assert "REFRESH-SECRET-NOPE" not in full_log


def test_token_store_repr_redacts():
    """TokenStore.__repr__ / __str__ must not include the actual
    access_token / refresh_token strings — any third-party logger
    that f-strings a token instance won't leak."""
    tok = TokenStore(
        access_token="VERY-SECRET",
        refresh_token="ALSO-SECRET",
        expires_at=time.time() + 1000,
        scope="scope",
    )
    r = repr(tok)
    assert "VERY-SECRET" not in r
    assert "ALSO-SECRET" not in r
    assert "<redacted>" in r
    assert "<set>" in r
    s = str(tok)
    assert s == r


# ---------------------------------------------------------------------------
# authorize_url shape
# ---------------------------------------------------------------------------


def test_authorize_url_includes_required_params(tmp_path: Path):
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=_StubTransport())
    url = o.authorize_url(state="xyz-state")
    assert url.startswith("https://example.test/oauth/authorize?")
    assert "client_id=client-id-abc" in url
    assert "response_type=code" in url
    assert "state=xyz-state" in url
    # Scopes space-joined then URL-encoded.
    assert "tweet.read" in url
    assert "users.read" in url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_parse_token_response_uses_fallback_refresh():
    """Vendors that don't echo refresh_token on a refresh call
    keep using the prior refresh_token — _parse_token_response
    handles that fallback."""
    tok = _parse_token_response(
        {"access_token": "new", "expires_in": 100},
        fallback_refresh="orig-refresh",
    )
    assert tok.refresh_token == "orig-refresh"
    assert tok.access_token == "new"


def test_parse_token_response_missing_access_token_raises():
    with pytest.raises(RuntimeError):
        _parse_token_response({"expires_in": 100}, fallback_refresh=None)


def test_redact_for_log_handles_no_token():
    tok = TokenStore(access_token="", refresh_token=None, expires_at=0)
    assert _redact_for_log(tok) == "(no token)"


def test_clear_removes_token(tmp_path: Path):
    o = SocialOAuth(_cfg(), token_dir=tmp_path, transport=_StubTransport(
        body={"access_token": "t", "refresh_token": "r", "expires_in": 1000}
    ))
    o.exchange("code")
    assert o.has_valid_token() is True
    assert o.clear() is True
    assert o.has_valid_token() is False
    assert o.clear() is False  # idempotent
