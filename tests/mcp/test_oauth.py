"""OAuth 2.1 PKCE flow + token storage."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from athena.mcp import oauth

# ---- PKCE pair generation -------------------------------------------


def test_pkce_pair_verifier_is_url_safe_base64() -> None:
    verifier, _ = oauth._gen_pkce_pair()
    # 32 bytes → 43 base64url-safe chars after padding strip.
    assert len(verifier) == 43
    base64.urlsafe_b64decode(verifier + "=" * (-len(verifier) % 4))


def test_pkce_pair_challenge_is_s256_of_verifier() -> None:
    verifier, challenge = oauth._gen_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert challenge == expected


def test_pkce_pair_is_random_each_call() -> None:
    v1, c1 = oauth._gen_pkce_pair()
    v2, c2 = oauth._gen_pkce_pair()
    assert v1 != v2
    assert c1 != c2


# ---- find_free_port -------------------------------------------------


def test_find_free_port_returns_usable_port() -> None:
    port = oauth._find_free_port()
    assert 1024 <= port <= 65535
    # Should be possible to bind again right after (briefly).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


# ---- authorization URL ----------------------------------------------


def test_build_authorization_url_carries_all_params() -> None:
    cfg = oauth.OAuthConfig(
        server_id="svc",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        client_id="my-client",
        scopes=["openid", "read:items"],
        audience="api.example.com",
    )
    url = oauth._build_authorization_url(
        cfg,
        redirect_uri="http://127.0.0.1:1234/callback",
        state="state-abc",
        challenge="challenge-xyz",
    )
    parsed = urlparse(url)
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == cfg.authorization_endpoint
    qs = parse_qs(parsed.query)
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["my-client"]
    assert qs["redirect_uri"] == ["http://127.0.0.1:1234/callback"]
    assert qs["scope"] == ["openid read:items"]
    assert qs["state"] == ["state-abc"]
    assert qs["code_challenge"] == ["challenge-xyz"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["audience"] == ["api.example.com"]


def test_build_authorization_url_omits_audience_when_unset() -> None:
    cfg = oauth.OAuthConfig(
        server_id="s",
        authorization_endpoint="https://auth.x/oauth",
        token_endpoint="https://auth.x/token",
        client_id="c",
        scopes=[],
    )
    url = oauth._build_authorization_url(
        cfg,
        redirect_uri="http://127.0.0.1:1/cb",
        state="s",
        challenge="c",
    )
    assert "audience" not in parse_qs(urlparse(url).query)


# ---- _await_callback -------------------------------------------------


async def test_await_callback_returns_code_on_success() -> None:
    port = oauth._find_free_port()
    task = asyncio.create_task(
        oauth._await_callback(port, state="my-state", timeout_seconds=5),
    )
    # Give the server a moment to bind.
    await asyncio.sleep(0.05)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        b"GET /callback?code=auth-code-123&state=my-state HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
    )
    await writer.drain()
    await reader.read()  # drain response so server can shut
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    code = await task
    assert code == "auth-code-123"


async def test_await_callback_rejects_state_mismatch() -> None:
    port = oauth._find_free_port()
    task = asyncio.create_task(
        oauth._await_callback(port, state="expected", timeout_seconds=5),
    )
    await asyncio.sleep(0.05)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /callback?code=c&state=wrong HTTP/1.1\r\nHost: x\r\n\r\n")
    await writer.drain()
    await reader.read()
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    with pytest.raises(oauth.OAuthError, match="state mismatch"):
        await task


async def test_await_callback_rejects_oauth_error_param() -> None:
    """Provider returns ?error=access_denied → propagate."""
    port = oauth._find_free_port()
    task = asyncio.create_task(
        oauth._await_callback(port, state="x", timeout_seconds=5),
    )
    await asyncio.sleep(0.05)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /callback?error=access_denied&state=x HTTP/1.1\r\nHost:x\r\n\r\n")
    await writer.drain()
    await reader.read()
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    with pytest.raises(oauth.OAuthError, match="access_denied"):
        await task


async def test_await_callback_times_out() -> None:
    port = oauth._find_free_port()
    with pytest.raises(oauth.OAuthError, match="timed out"):
        await oauth._await_callback(port, state="x", timeout_seconds=0.05)


# ---- token exchange / refresh --------------------------------------


def _cfg(token_url: str = "https://auth.example.com/token") -> oauth.OAuthConfig:
    return oauth.OAuthConfig(
        server_id="linear",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint=token_url,
        client_id="cli-abc",
        scopes=["read"],
    )


async def test_exchange_code_returns_stored_token() -> None:
    cfg = _cfg()
    async with respx.mock(base_url="https://auth.example.com") as mock:
        mock.post("/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "AT-123",
                    "refresh_token": "RT-456",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "read",
                },
            )
        )
        token = await oauth._exchange_code_for_token(
            cfg,
            code="c",
            verifier="v",
            redirect_uri="http://127.0.0.1:1/cb",
        )

    assert token.access_token == "AT-123"
    assert token.refresh_token == "RT-456"
    assert token.token_type == "Bearer"
    assert token.scope == "read"
    delta = (token.expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 3550 < delta < 3650  # ~1 hour from now


async def test_exchange_code_failure_raises_oauth_error() -> None:
    cfg = _cfg()
    async with respx.mock(base_url="https://auth.example.com") as mock:
        mock.post("/token").mock(return_value=httpx.Response(400, text='{"error":"invalid_grant"}'))
        with pytest.raises(oauth.OAuthError, match="invalid_grant"):
            await oauth._exchange_code_for_token(
                cfg,
                code="c",
                verifier="v",
                redirect_uri="x",
            )


async def test_refresh_returns_new_token() -> None:
    cfg = _cfg()
    old = oauth.StoredToken(
        access_token="OLD",
        refresh_token="RT-old",
        expires_at=datetime.now(timezone.utc),
        scope="read",
    )
    async with respx.mock(base_url="https://auth.example.com") as mock:
        mock.post("/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "NEW",
                    "refresh_token": "RT-new",
                    "expires_in": 1800,
                },
            )
        )
        new = await oauth.refresh_async(cfg, old)
    assert new.access_token == "NEW"
    assert new.refresh_token == "RT-new"


async def test_refresh_preserves_prior_refresh_token_when_omitted() -> None:
    """If the provider doesn't rotate refresh tokens, keep ours."""
    cfg = _cfg()
    old = oauth.StoredToken(
        access_token="OLD",
        refresh_token="RT-old",
        expires_at=datetime.now(timezone.utc),
        scope="read",
    )
    async with respx.mock(base_url="https://auth.example.com") as mock:
        mock.post("/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "NEW",
                    "expires_in": 600,
                    # No refresh_token in response.
                },
            )
        )
        new = await oauth.refresh_async(cfg, old)
    assert new.refresh_token == "RT-old"


async def test_refresh_preserves_scope_when_omitted() -> None:
    cfg = _cfg()
    old = oauth.StoredToken(
        access_token="OLD",
        refresh_token="RT",
        expires_at=datetime.now(timezone.utc),
        scope="read:all",
    )
    async with respx.mock(base_url="https://auth.example.com") as mock:
        mock.post("/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "NEW",
                    "expires_in": 600,
                },
            )
        )
        new = await oauth.refresh_async(cfg, old)
    assert new.scope == "read:all"


async def test_refresh_raises_when_no_refresh_token() -> None:
    cfg = _cfg()
    old = oauth.StoredToken(
        access_token="OLD",
        refresh_token=None,
        expires_at=datetime.now(timezone.utc),
    )
    with pytest.raises(oauth.OAuthError, match="no refresh_token"):
        await oauth.refresh_async(cfg, old)


async def test_refresh_failure_raises() -> None:
    cfg = _cfg()
    old = oauth.StoredToken(
        access_token="OLD",
        refresh_token="RT",
        expires_at=datetime.now(timezone.utc),
    )
    async with respx.mock(base_url="https://auth.example.com") as mock:
        mock.post("/token").mock(return_value=httpx.Response(401, text="bad"))
        with pytest.raises(oauth.OAuthError, match="401"):
            await oauth.refresh_async(cfg, old)


# ---- needs_refresh helper -----------------------------------------


def test_needs_refresh_true_within_grace() -> None:
    token = oauth.StoredToken(
        access_token="x",
        refresh_token="r",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    assert token.needs_refresh is True


def test_needs_refresh_false_when_fresh() -> None:
    token = oauth.StoredToken(
        access_token="x",
        refresh_token="r",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert token.needs_refresh is False


def test_needs_refresh_true_when_already_expired() -> None:
    token = oauth.StoredToken(
        access_token="x",
        refresh_token="r",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    assert token.needs_refresh is True
