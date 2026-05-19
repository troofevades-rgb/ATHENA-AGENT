"""OAuth 2.1 with PKCE for MCP HTTP/SSE servers.

The MCP spec mandates OAuth 2.1 for authenticated HTTP/SSE servers
(Linear, Atlassian, Sentry, Smithery, etc.). PKCE is required — we
never use the deprecated implicit flow.

The flow:

1. Generate a code verifier + S256 challenge.
2. Open a local one-shot callback server on ``127.0.0.1:<free-port>``.
3. Open the user's browser at the provider's authorization endpoint,
   passing client_id, redirect_uri (our local server), state, scope,
   and the code_challenge.
4. Wait for the browser to redirect back with ``?code=…&state=…``.
5. Validate ``state`` against what we sent (CSRF defense).
6. POST the code + verifier to the token endpoint, get back an access
   token + refresh token.
7. Save the token at ``~/.athena/mcp_tokens/<server_id>.json`` with
   mode 0600.

Refresh: when an access token has < ~2 minutes until expiry, call
:func:`refresh` to swap for a fresh pair. If no refresh_token is
present (provider didn't issue one — rare for OAuth 2.1 but legal)
:class:`OAuthError` surfaces so the caller knows to trigger a fresh
:func:`run_authorization_flow`.

The async functions are the actual implementations; the sync wrappers
(:func:`run_authorization_flow`, :func:`refresh`) drive an event loop
internally so callers from synchronous MCP code (athena/mcp/client.py
is sync) don't need to be aware of asyncio.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import socket
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import CONFIG_DIR
from ..safety.secure_files import ensure_secure_dir, secure_read_text, secure_write_json

logger = logging.getLogger(__name__)


TOKENS_DIR = CONFIG_DIR / "mcp_tokens"
"""Where StoredTokens live on disk. One JSON file per server_id."""

# Refresh proactively when within this window of expiry. Keeps us from
# the worst-case "token expired between check and request" race.
_REFRESH_GRACE = timedelta(minutes=2)


class OAuthError(RuntimeError):
    """Anything that goes wrong during the OAuth dance."""


@dataclass
class OAuthConfig:
    """Per-server OAuth configuration. Lives in ``mcp.json`` under
    the server's ``oauth`` key alongside its transport settings.

    ``audience`` is optional — Auth0-style providers want it; many
    others ignore it. We pass it through when set.
    """

    server_id: str
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    scopes: list[str] = field(default_factory=list)
    audience: str | None = None


@dataclass
class StoredToken:
    """On-disk token record."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime
    token_type: str = "Bearer"
    scope: str = ""

    @property
    def needs_refresh(self) -> bool:
        return (self.expires_at - datetime.now(timezone.utc)) < _REFRESH_GRACE


# ---- helpers ----------------------------------------------------------


def _gen_pkce_pair() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` per RFC 7636 / OAuth 2.1.

    The verifier is 43–128 base64url-safe chars; we use 32 random
    bytes → 43 chars after base64-encoding and stripping ``=``.
    The challenge is the S256 hash of the verifier.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _find_free_port() -> int:
    """Ask the OS for a free port. The bind+release window is
    technically racy but the OS won't reassign it for several seconds
    on any modern stack — long enough to bind for real in the caller.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_authorization_url(
    cfg: OAuthConfig,
    *,
    redirect_uri: str,
    state: str,
    challenge: str,
) -> str:
    """Compose the authorization endpoint URL from PKCE inputs."""
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(cfg.scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if cfg.audience:
        params["audience"] = cfg.audience
    return f"{cfg.authorization_endpoint}?{urlencode(params)}"


# ---- authorization flow -----------------------------------------------


async def run_authorization_flow_async(
    cfg: OAuthConfig,
    *,
    open_browser: bool = True,
    timeout_seconds: int = 300,
    transport: httpx.AsyncBaseTransport | None = None,
) -> StoredToken:
    """Drive the full PKCE flow and return the resulting token.

    ``transport`` is injected for tests — production passes None and
    a default httpx client gets constructed for the token exchange.
    """
    verifier, challenge = _gen_pkce_pair()
    port = _find_free_port()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = secrets.token_urlsafe(16)

    auth_url = _build_authorization_url(
        cfg,
        redirect_uri=redirect_uri,
        state=state,
        challenge=challenge,
    )

    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            logger.debug("webbrowser.open failed; printing URL", exc_info=True)
            print(f"Open this URL to authenticate:\n{auth_url}", file=sys.stderr)
    else:
        print(f"Open this URL to authenticate:\n{auth_url}", file=sys.stderr)

    code = await _await_callback(port, state, timeout_seconds=timeout_seconds)
    return await _exchange_code_for_token(
        cfg,
        code=code,
        verifier=verifier,
        redirect_uri=redirect_uri,
        transport=transport,
    )


async def _await_callback(
    port: int,
    state: str,
    *,
    timeout_seconds: int,
) -> str:
    """Bind a one-shot HTTP server on 127.0.0.1:port; wait for
    ``GET /callback?code=…&state=…``. Returns the code on success or
    raises :class:`OAuthError`.

    The server auto-shuts on first hit (or timeout) so we don't leave
    a port open. State mismatch → reject (CSRF defense).
    """
    loop = asyncio.get_event_loop()
    code_fut: asyncio.Future[str] = loop.create_future()

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            # Drain the rest of headers so curl-like clients don't hang.
            while True:
                header = await reader.readline()
                if header in (b"\r\n", b""):
                    break
            from urllib.parse import parse_qs, urlparse

            parts = request_line.decode("latin-1", errors="replace").split(" ")
            if len(parts) < 2:
                _write_simple(writer, 400, "<h1>bad request</h1>")
                return
            qs = parse_qs(urlparse(parts[1]).query)
            if "error" in qs:
                _write_simple(
                    writer,
                    400,
                    f"<h1>OAuth error: {qs['error'][0]}</h1>",
                )
                if not code_fut.done():
                    code_fut.set_exception(
                        OAuthError(qs["error"][0]),
                    )
                return
            if qs.get("state", [""])[0] != state:
                _write_simple(writer, 400, "<h1>state mismatch</h1>")
                if not code_fut.done():
                    code_fut.set_exception(OAuthError("state mismatch"))
                return
            code_values = qs.get("code") or []
            if not code_values:
                _write_simple(writer, 400, "<h1>no code in callback</h1>")
                if not code_fut.done():
                    code_fut.set_exception(OAuthError("no code"))
                return
            _write_simple(
                writer,
                200,
                "<h1>Authentication complete. You can close this tab.</h1>",
            )
            if not code_fut.done():
                code_fut.set_result(code_values[0])
        except Exception as e:
            logger.exception("callback handler raised")
            if not code_fut.done():
                code_fut.set_exception(OAuthError(str(e)))
        finally:
            try:
                await writer.drain()
            except Exception:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(_handler, "127.0.0.1", port)
    try:
        code = await asyncio.wait_for(code_fut, timeout=timeout_seconds)
    except asyncio.TimeoutError as e:
        raise OAuthError(
            f"timed out waiting for OAuth callback after {timeout_seconds}s",
        ) from e
    finally:
        server.close()
        try:
            await server.wait_closed()
        except Exception:
            pass
    return code


def _write_simple(writer: asyncio.StreamWriter, status: int, body: str) -> None:
    status_text = {200: "OK", 400: "Bad Request"}.get(status, "OK")
    payload = (
        f"HTTP/1.1 {status} {status_text}\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body.encode())}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    writer.write(payload + body.encode())


async def _exchange_code_for_token(
    cfg: OAuthConfig,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> StoredToken:
    """POST to the token endpoint with the authorization code +
    PKCE verifier. Return the resulting StoredToken."""
    async with httpx.AsyncClient(transport=transport, timeout=20.0) as client:
        r = await client.post(
            cfg.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": cfg.client_id,
                "code_verifier": verifier,
            },
        )
        if r.status_code >= 400:
            raise OAuthError(f"token endpoint returned {r.status_code}: {(r.text or '')[:500]}")
        body = r.json()

    return _stored_token_from_response(body)


def _stored_token_from_response(body: dict[str, Any]) -> StoredToken:
    expires_in = int(body.get("expires_in") or 3600)
    return StoredToken(
        access_token=str(body["access_token"]),
        refresh_token=body.get("refresh_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        token_type=str(body.get("token_type") or "Bearer"),
        scope=str(body.get("scope") or ""),
    )


async def refresh_async(
    cfg: OAuthConfig,
    token: StoredToken,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> StoredToken:
    """Use the refresh_token grant to swap for a fresh access token.

    If the provider rotates refresh tokens, the new one comes back in
    the response — we propagate it. If not (some providers don't),
    keep the prior refresh_token so we can refresh again later.
    """
    if not token.refresh_token:
        raise OAuthError("no refresh_token available; re-auth required")
    async with httpx.AsyncClient(transport=transport, timeout=20.0) as client:
        r = await client.post(
            cfg.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "client_id": cfg.client_id,
            },
        )
        if r.status_code >= 400:
            raise OAuthError(f"refresh failed {r.status_code}: {(r.text or '')[:500]}")
        body = r.json()
    new_token = _stored_token_from_response(body)
    # Preserve the rotation chain when the provider doesn't issue a
    # fresh refresh_token.
    if not new_token.refresh_token:
        new_token.refresh_token = token.refresh_token
    if not new_token.scope:
        new_token.scope = token.scope
    return new_token


# ---- sync façades --------------------------------------------------


def run_authorization_flow(
    cfg: OAuthConfig,
    *,
    open_browser: bool = True,
    timeout_seconds: int = 300,
) -> StoredToken:
    """Sync entry point. Drives the async flow via :func:`asyncio.run`.

    Callers from synchronous MCP code (athena/mcp/client.py) use this
    so they don't need to spin up their own event loop.
    """
    return asyncio.run(
        run_authorization_flow_async(
            cfg,
            open_browser=open_browser,
            timeout_seconds=timeout_seconds,
        )
    )


def refresh(cfg: OAuthConfig, token: StoredToken) -> StoredToken:
    """Sync façade for :func:`refresh_async`."""
    return asyncio.run(refresh_async(cfg, token))


# ---- on-disk persistence -------------------------------------------


def _token_path(server_id: str) -> Path:
    if not server_id:
        raise ValueError("server_id must be non-empty")
    if "/" in server_id or "\\" in server_id or ".." in server_id:
        raise ValueError(f"server_id contains invalid chars: {server_id!r}")
    return TOKENS_DIR / f"{server_id}.json"


def save_token(server_id: str, token: StoredToken) -> None:
    """Atomically write the token with mode 0o600 via secure_files.

    ``secure_write_json`` uses ``os.open(O_EXCL, 0o600)`` so the file
    never exists at a wider mode. ``ensure_secure_dir`` brings
    ``~/.athena/mcp_tokens/`` up to 0o700 on first call.
    """
    ensure_secure_dir(TOKENS_DIR)
    path = _token_path(server_id)
    payload = {
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "expires_at": token.expires_at.isoformat(),
        "token_type": token.token_type,
        "scope": token.scope,
    }
    secure_write_json(path, payload)


def load_token(server_id: str) -> StoredToken | None:
    """Return the persisted token for ``server_id``, or ``None`` if
    no file is present / parse fails."""
    path = _token_path(server_id)
    if not path.exists():
        return None
    try:
        data = json.loads(secure_read_text(path))
    except (OSError, json.JSONDecodeError):
        logger.warning("failed to parse token file %s", path, exc_info=True)
        return None
    try:
        return StoredToken(
            access_token=str(data["access_token"]),
            refresh_token=data.get("refresh_token"),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            token_type=str(data.get("token_type") or "Bearer"),
            scope=str(data.get("scope") or ""),
        )
    except (KeyError, ValueError, TypeError):
        logger.warning(
            "token file %s missing required fields",
            path,
            exc_info=True,
        )
        return None


def delete_token(server_id: str) -> bool:
    """Remove the on-disk token. Returns True iff a file existed."""
    path = _token_path(server_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def list_token_status() -> dict[str, dict[str, Any]]:
    """Return ``{server_id: {expires_at, expires_in_seconds, scope}}``
    for every stored token. Used by ``athena mcp token-status``.
    """
    if not TOKENS_DIR.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for p in sorted(TOKENS_DIR.glob("*.json")):
        if p.name.endswith(".tmp.json"):
            continue
        server_id = p.stem
        token = load_token(server_id)
        if token is None:
            continue
        delta = (token.expires_at - now).total_seconds()
        out[server_id] = {
            "expires_at": token.expires_at.isoformat(),
            "expires_in_seconds": int(delta),
            "scope": token.scope,
            "has_refresh_token": token.refresh_token is not None,
        }
    return out
