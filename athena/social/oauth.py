"""OAuth flow for the social provider — vendor specifics isolated (T6-02.2).

A single tight contract:

  SocialOAuth(cfg).has_valid_token() -> bool
  SocialOAuth(cfg).access_token()    -> str   # refreshes if expired
  SocialOAuth(cfg).authorize_url(state)
                                     -> str   # user opens in a browser
  SocialOAuth(cfg).exchange(code)    -> None  # stores token via secrets

Tokens never live in plaintext config and never appear in logs.
Persistence goes through :mod:`athena.safety.secure_files` at
0o600 with the same atomic-replace + fsync semantics every other
credential file in athena gets. Logging is sanitised at the
adapter boundary — the only logger call that handles token-shaped
strings is :func:`_redact_for_log`.

ALL vendor specifics (endpoint URLs, scopes, the token-endpoint
response shape) are isolated to:

  - ``cfg.social_oauth_authorize_url``
  - ``cfg.social_oauth_token_url``
  - ``cfg.social_oauth_client_id``
  - ``cfg.social_oauth_client_secret_path``  (file with the secret)
  - ``cfg.social_oauth_scopes``
  - ``cfg.social_oauth_redirect_uri``

A vendor change → edit those config entries + the adapter; nothing
else in athena needs to know.

Tests stub the token endpoint (HTTP transport injected at
construction). No live network calls.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from ..safety.secure_files import secure_read_json, secure_write_json

logger = logging.getLogger(__name__)


_TOKEN_FILENAME = "social_token.json"
# Tokens within this window of expiring are pre-emptively refreshed.
_REFRESH_LEEWAY_S = 60


@dataclasses.dataclass
class TokenStore:
    """One stored OAuth token bundle.

    Persistence goes through ``secure_files`` so the file is
    created at 0o600 atomically. The structure here is what the
    JSON on disk looks like — the adapter never logs an
    instance directly (the repr is overridden to redact).
    """

    access_token: str
    refresh_token: str | None
    expires_at: float  # epoch seconds; 0 → never (or unknown)
    scope: str = ""
    token_type: str = "Bearer"

    # Don't ever leak token material via repr / str.
    def __repr__(self) -> str:  # noqa: D401 — short
        return (
            f"TokenStore(scope={self.scope!r}, "
            f"expires_at={self.expires_at!r}, "
            f"token_type={self.token_type!r}, access_token=<redacted>, "
            f"refresh_token={'<set>' if self.refresh_token else '<none>'})"
        )

    __str__ = __repr__

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TokenStore:
        return cls(
            access_token=str(d.get("access_token", "")),
            refresh_token=(
                str(d["refresh_token"]) if d.get("refresh_token") else None
            ),
            expires_at=float(d.get("expires_at", 0.0)),
            scope=str(d.get("scope", "")),
            token_type=str(d.get("token_type", "Bearer")),
        )

    def is_alive(self, *, now: float | None = None, leeway: int = _REFRESH_LEEWAY_S) -> bool:
        """Is the token usable without refresh? ``expires_at == 0``
        is interpreted as "no expiry known" — we still treat it
        as alive (the vendor's call will refuse if it's actually
        dead, and the adapter retries via refresh)."""
        if not self.access_token:
            return False
        if self.expires_at <= 0:
            return True
        return ((now or time.time()) + leeway) < self.expires_at


# Transport callable contract: HTTP POST with form-encoded body,
# returns (status, json_body). Injected so tests stub it without
# any real network.
TokenEndpointFn = Callable[[str, dict[str, str]], "TokenResponse"]


@dataclasses.dataclass
class TokenResponse:
    """Normalised shape returned by the token endpoint transport.

    Vendors return JSON with at least ``access_token``,
    optionally ``refresh_token``, and an ``expires_in`` second
    count. ``raw`` is the parsed JSON for the adapter to peek
    into vendor-specific extras if needed.
    """

    status: int
    body: dict[str, Any]


class SocialOAuth:
    """Adapter for the social provider's OAuth2 authorization-code
    flow with refresh.

    Surface (keep tight; the rest of athena doesn't need more):

      ``has_valid_token()``     bool, fast check
      ``access_token()``        str, refreshes if expired
      ``authorize_url(state)``  build the URL the user opens
      ``exchange(code, ...)``   one-shot code → token, persists
      ``clear()``               wipe the on-disk token

    Everything else is internal.
    """

    def __init__(
        self,
        cfg: Any,
        *,
        token_dir: Path | str | None = None,
        transport: TokenEndpointFn | None = None,
    ):
        self.cfg = cfg
        self._token_dir = Path(token_dir) if token_dir else _default_token_dir(cfg)
        self._transport = transport or _default_transport
        self._cached: TokenStore | None = None

    # ------------------------------------------------------------------
    # State checks
    # ------------------------------------------------------------------

    def has_valid_token(self) -> bool:
        """``True`` iff a non-expired token is on disk. Does NOT
        refresh — used as a cheap "is this provider configured"
        gate by ``SocialProvider.is_available``."""
        tok = self._load()
        return tok is not None and tok.is_alive()

    def access_token(self) -> str:
        """Return a usable access token, refreshing if the stored
        one is expired. Raises ``RuntimeError`` when no token
        exists (caller should run the authorize flow first) and
        when refresh fails with no fallback."""
        tok = self._load()
        if tok is None:
            raise RuntimeError(
                "no social token on disk; run the authorize flow first"
            )
        if tok.is_alive():
            return tok.access_token
        if not tok.refresh_token:
            raise RuntimeError(
                "stored token expired and no refresh_token available; re-run authorize"
            )
        refreshed = self._refresh(tok.refresh_token)
        return refreshed.access_token

    # ------------------------------------------------------------------
    # Authorize flow
    # ------------------------------------------------------------------

    def authorize_url(self, state: str = "") -> str:
        """Build the URL the user opens in a browser to grant
        access. ``state`` is the CSRF-protection token the caller
        will verify on the callback."""
        base = _required(self.cfg, "social_oauth_authorize_url")
        params = {
            "response_type": "code",
            "client_id": _required(self.cfg, "social_oauth_client_id"),
            "redirect_uri": _required(self.cfg, "social_oauth_redirect_uri"),
            "scope": " ".join(getattr(self.cfg, "social_oauth_scopes", []) or []),
            "state": state or "",
        }
        return f"{base}?{urllib.parse.urlencode(params)}"

    def exchange(self, code: str, *, code_verifier: str | None = None) -> TokenStore:
        """Exchange a single-use authorization ``code`` for a
        token. PKCE-aware: pass ``code_verifier`` when the
        original authorize call included a ``code_challenge``.
        Persists the resulting token via ``secure_files``."""
        if not code:
            raise ValueError("authorization code required")
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _required(self.cfg, "social_oauth_redirect_uri"),
            "client_id": _required(self.cfg, "social_oauth_client_id"),
        }
        secret = _read_client_secret(self.cfg)
        if secret:
            body["client_secret"] = secret
        if code_verifier:
            body["code_verifier"] = code_verifier
        return self._post_token(body, kind="exchange")

    def clear(self) -> bool:
        """Drop the on-disk token. Returns ``True`` if a token
        existed. The cached in-memory copy is invalidated too."""
        path = self._token_path()
        existed = path.exists()
        if existed:
            path.unlink()
        self._cached = None
        return existed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refresh(self, refresh_token: str) -> TokenStore:
        body = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": _required(self.cfg, "social_oauth_client_id"),
        }
        secret = _read_client_secret(self.cfg)
        if secret:
            body["client_secret"] = secret
        return self._post_token(body, kind="refresh")

    def _post_token(self, body: dict[str, str], *, kind: str) -> TokenStore:
        url = _required(self.cfg, "social_oauth_token_url")
        try:
            resp = self._transport(url, body)
        except Exception as e:  # noqa: BLE001
            # Token-endpoint errors are summarised — the body is
            # likely vendor-specific JSON we'd rather not log
            # opaquely.
            logger.warning("social oauth %s transport failed: %s", kind, e)
            raise RuntimeError(f"social oauth {kind} failed: transport error") from e
        if resp.status != 200:
            logger.warning(
                "social oauth %s returned HTTP %s", kind, resp.status
            )
            raise RuntimeError(
                f"social oauth {kind} failed: HTTP {resp.status}"
            )
        token = _parse_token_response(resp.body, fallback_refresh=body.get("refresh_token"))
        self._persist(token)
        logger.info(
            "social oauth %s succeeded (scope=%s, expires_in=%s)",
            kind,
            token.scope,
            _redact_for_log(token),
        )
        return token

    def _persist(self, token: TokenStore) -> None:
        secure_write_json(self._token_path(), token.to_dict(), mode=0o600)
        self._cached = token

    def _load(self) -> TokenStore | None:
        if self._cached is not None:
            return self._cached
        path = self._token_path()
        if not path.exists():
            return None
        try:
            raw = secure_read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        try:
            tok = TokenStore.from_dict(raw)
        except (TypeError, KeyError, ValueError):
            return None
        self._cached = tok
        return tok

    def _token_path(self) -> Path:
        self._token_dir.mkdir(parents=True, exist_ok=True)
        return self._token_dir / _TOKEN_FILENAME


# ---------------------------------------------------------------------------
# Helpers — kept module-level so tests can patch / call them directly
# ---------------------------------------------------------------------------


def _parse_token_response(
    body: dict[str, Any], *, fallback_refresh: str | None
) -> TokenStore:
    """Map a vendor token response to :class:`TokenStore`.

    The standard OAuth2 shape — ``{"access_token", "refresh_token",
    "expires_in", "scope", "token_type"}`` — is what every modern
    social vendor returns. Vendor extras are ignored here; the
    adapter exposes raw response info only via debug logging if
    needed (none here today).
    """
    if "access_token" not in body:
        raise RuntimeError(
            "social oauth response missing access_token"
        )
    expires_in = float(body.get("expires_in") or 0)
    expires_at = (time.time() + expires_in) if expires_in > 0 else 0.0
    refresh = body.get("refresh_token") or fallback_refresh
    return TokenStore(
        access_token=str(body["access_token"]),
        refresh_token=str(refresh) if refresh else None,
        expires_at=expires_at,
        scope=str(body.get("scope", "")),
        token_type=str(body.get("token_type", "Bearer")),
    )


def _redact_for_log(token: TokenStore) -> str:
    """The only function permitted to format token info for logs.

    Returns the bits a human needs (was it received, when does it
    expire) and NEVER the token material."""
    if not token.access_token:
        return "(no token)"
    if token.expires_at <= 0:
        return "(no expiry recorded)"
    return f"{int(token.expires_at - time.time())}s remaining"


def _required(cfg: Any, name: str) -> str:
    value = getattr(cfg, name, None)
    if not value:
        raise RuntimeError(
            f"social oauth config missing: cfg.{name}. "
            "Set it before invoking the adapter."
        )
    return str(value)


def _read_client_secret(cfg: Any) -> str | None:
    """Read the OAuth client secret from the path in cfg, or None
    when no path is configured (some flows don't need one)."""
    path = getattr(cfg, "social_oauth_client_secret_path", None)
    if not path:
        return None
    p = Path(str(path)).expanduser()
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _default_token_dir(cfg: Any) -> Path:
    """Default token directory: ``<profile_dir>/social/``."""
    from ..config import profile_dir as _pd

    profile = getattr(cfg, "profile", None) or "default"
    return _pd(profile) / "social"


def _default_transport(url: str, body: dict[str, str]) -> TokenResponse:
    """Real HTTP transport. urllib + form-encoded body. The
    standard library is enough — no extra dependency for a single
    token endpoint hit. Tests inject a stub via the constructor;
    this function is only exercised at run time."""
    import urllib.request

    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — vendor URL
            status = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return TokenResponse(status=e.code, body={})
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    return TokenResponse(status=status, body=parsed if isinstance(parsed, dict) else {})
