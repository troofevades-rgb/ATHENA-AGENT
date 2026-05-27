"""Social provider — declares social_search, not chat (T6-02.3).

This provider's role in the registry is narrow: it exists so the
T5-05 broker's ``best_for({"social_search"})`` lookup has
something to return. The agent doesn't chat with this provider;
it routes the :func:`athena.social.search.run_search_x` sub-task
to it, then folds the normalised results back into the primary
model's context.

stream_chat / parse_tool_calls are implemented for the Provider
ABC contract but raise / no-op respectively — the broker won't
route a chat here because the manifest doesn't declare
``tool_calls=True`` for streaming use. If something does try to
chat with the social provider, the explicit error is clearer
than a silent miss.

Vendor specifics (the actual search endpoint URL + response
shape) live in :meth:`SocialProvider.social_search` along with
the OAuth adapter — one or two files to swap a vendor.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

from . import register_provider
from .base import Capabilities, Provider, StreamChunk

logger = logging.getLogger(__name__)


# Normalised result shape the primary model sees:
#   {author, text, timestamp, url, metrics?}
# A list of these is what run_search_x returns to the agent.
_DEFAULT_MAX_RESULTS = 20


@register_provider
class SocialProvider(Provider):
    """Capability-only social-search provider.

    Construction can be argument-free (the OAuth adapter reads
    from cfg / disk); a credential pool entry is not required —
    this provider's "auth" is the OAuth-stored access token, not
    an API key.

    The constructor optionally takes ``oauth`` for tests to inject
    a stubbed :class:`athena.social.oauth.SocialOAuth`. In
    production the adapter is built lazily on first
    :meth:`social_search` call from the active config.
    """

    name = "social"
    requires_api_key = False  # OAuth-only

    def __init__(
        self,
        api_key: str | None = None,
        *,
        oauth: Any = None,
        transport: Any = None,
        cfg: Any = None,
        **kwargs: Any,
    ):
        super().__init__(api_key=api_key, **kwargs)
        self._oauth = oauth
        self._transport = transport
        self._cfg_override = cfg

    # ------------------------------------------------------------------
    # Capabilities — declares social_search only
    # ------------------------------------------------------------------

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        """The social provider declares ``social_search=True``
        and nothing else extra. tool_calls / streaming default
        True for ABC compatibility but the broker never routes
        chat here because nothing keys off social as a chat
        backend."""
        return Capabilities(
            social_search=True,
            tool_calls=False,  # not a chat backend
            streaming=False,
            is_local=False,
        )

    def is_available(self) -> bool:
        """Cheap "has the user authorised this provider yet"
        check the differentiated MCP surface + the search tool's
        graceful-when-absent path consult.

        Two paths considered, in this order:

          1. ``cfg.social_bearer_token_path`` — app-only bearer
             token (X / Twitter v2 style). Single string in a
             0o600 file; skip OAuth entirely.
          2. OAuth 2.0 user-context token persisted via
             :class:`SocialOAuth`.

        Either path satisfies — the provider doesn't care which
        one ended up loading the token. Defensive: any
        exception in either path returns False (the search tool
        surfaces "no provider configured" rather than crashing
        a turn)."""
        if _read_bearer_token(self._cfg()):
            return True
        try:
            return self._get_oauth().has_valid_token()
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # social_search — the actual capability
    # ------------------------------------------------------------------

    def social_search(
        self,
        query: str,
        *,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> list[dict[str, Any]]:
        """Search the configured social provider for posts matching
        ``query``. Returns up to ``max_results`` items in the
        normalised shape ``{author, text, timestamp, url,
        metrics?}``.

        Vendor specifics:

          * search URL — ``cfg.social_search_url`` (build-time)
          * query param name — ``cfg.social_search_query_param``
            (defaults to ``"query"``)
          * response mapping — :meth:`_normalise_response` reads
            the response shape this vendor uses

        Token comes from the OAuth adapter; refreshes
        automatically if expired. Returns ``[]`` (with a debug
        log) rather than raising when the request fails — the
        primary model gets "no results" and can move on instead
        of crashing the turn.
        """
        if not query.strip():
            return []

        cfg = self._cfg()
        access_token = self._resolve_token(cfg)
        if access_token is None:
            return []

        url_base = getattr(cfg, "social_search_url", None)
        if not url_base:
            logger.warning(
                "social search: cfg.social_search_url not configured"
            )
            return []
        query_param = getattr(cfg, "social_search_query_param", "query")
        params = {
            query_param: query,
            "max_results": int(max_results),
        }
        # Vendor extras can be merged from cfg if they need to.
        extras = getattr(cfg, "social_search_extra_params", None) or {}
        params.update(extras)
        full_url = f"{url_base}?{urllib.parse.urlencode(params)}"
        body = self._get(full_url, access_token=access_token)
        if not body:
            return []
        return self._normalise_response(body, limit=int(max_results))

    # ------------------------------------------------------------------
    # user_lookup — resolve username → user ID + profile
    # ------------------------------------------------------------------

    def user_lookup(self, username: str) -> dict[str, Any] | None:
        """Resolve an X / social username to a user object.

        Returns ``{id, username, name, description, ...}`` or None
        when the user doesn't exist or the endpoint fails.

        Endpoint: ``cfg.social_user_lookup_url`` — the URL up to
        but NOT including the username segment. The username is
        appended as a path component (X v2 shape:
        ``/2/users/by/username/:username``).
        """
        username = username.lstrip("@").strip()
        if not username:
            return None

        cfg = self._cfg()
        access_token = self._resolve_token(cfg)
        if access_token is None:
            return None

        url_base = getattr(cfg, "social_user_lookup_url", None)
        if not url_base:
            logger.warning("social user_lookup: cfg.social_user_lookup_url not configured")
            return None

        params = {
            "user.fields": "description,created_at,public_metrics,profile_image_url,location,url,verified",
        }
        full_url = f"{url_base.rstrip('/')}/{urllib.parse.quote(username, safe='')}?{urllib.parse.urlencode(params)}"
        body = self._get(full_url, access_token=access_token)
        if not body:
            return None
        data = body.get("data")
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------
    # user_timeline — fetch a user's posts by user ID
    # ------------------------------------------------------------------

    def user_timeline(
        self,
        user_id: str,
        *,
        max_results: int | None = None,
        max_pages: int = 1,
        pagination_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch posts for a user by their numeric ID.

        Supports multi-page pagination to walk deeper into a
        user's history. X v2 returns up to 100 tweets per page
        and a ``next_token`` for the next page.

        Args:
            user_id: Numeric user ID.
            max_results: Total posts wanted across all pages.
            max_pages: Max API pages to fetch (each up to 100
                tweets). Caps total API calls. Default 1.
            pagination_token: Resume from a previous page.

        Returns:
            ``(posts, next_token)`` — normalised posts and the
            token to continue from (None when exhausted).
        """
        if not user_id or not str(user_id).strip():
            return [], None

        cfg = self._cfg()
        access_token = self._resolve_token(cfg)
        if access_token is None:
            return [], None

        url_base = getattr(cfg, "social_user_timeline_url", None)
        if not url_base:
            logger.warning("social user_timeline: cfg.social_user_timeline_url not configured")
            return [], None

        total_wanted = int(max_results) if max_results else int(
            getattr(cfg, "social_user_timeline_max_results", 50)
        )
        per_page = min(total_wanted, 100)

        base_params: dict[str, Any] = {
            "max_results": per_page,
            "tweet.fields": "created_at,public_metrics,referenced_tweets,conversation_id",
            "expansions": "author_id",
            "user.fields": "username,name",
        }
        extras = getattr(cfg, "social_user_timeline_extra_params", None) or {}
        base_params.update(extras)

        all_posts: list[dict[str, Any]] = []
        next_token = pagination_token

        for _page in range(max(1, int(max_pages))):
            params = dict(base_params)
            if next_token:
                params["pagination_token"] = next_token

            full_url = f"{url_base.rstrip('/')}/{user_id}/tweets?{urllib.parse.urlencode(params)}"
            body = self._get(full_url, access_token=access_token)
            if not body:
                break

            page_posts = self._normalise_response(body, limit=per_page)
            all_posts.extend(page_posts)

            meta = body.get("meta")
            next_token = meta.get("next_token") if isinstance(meta, dict) else None
            if not next_token or len(all_posts) >= total_wanted:
                break

        return all_posts[:total_wanted], next_token

    # ------------------------------------------------------------------
    # Provider ABC plumbing — social isn't a chat backend
    # ------------------------------------------------------------------

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        raise NotImplementedError(
            "the social provider is search-only — route via "
            "best_for({'social_search'}) instead of using it as "
            "a chat backend"
        )

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        return content, []

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_token(self, cfg: Any) -> str | None:
        """Bearer-first, OAuth-fallback token resolution."""
        access_token = _read_bearer_token(cfg)
        if access_token is None:
            try:
                access_token = self._get_oauth().access_token()
            except Exception as e:  # noqa: BLE001
                logger.warning("social: no token available: %s", e)
                return None
        return access_token

    def _get_oauth(self):
        if self._oauth is not None:
            return self._oauth
        from ..social.oauth import SocialOAuth

        self._oauth = SocialOAuth(self._cfg())
        return self._oauth

    def _cfg(self):
        if self._cfg_override is not None:
            return self._cfg_override
        from ..config import load_config

        return load_config()

    def _get(self, url: str, *, access_token: str) -> dict[str, Any] | None:
        """HTTP GET with the OAuth / bearer token. Returns the
        parsed JSON body, or None on transport / decode failure.
        Injectable transport for tests (cfg-aware fallback to
        ``urllib`` in production).

        On HTTPError (4xx/5xx) the response body is read +
        included in the warning log so an operator can see the
        vendor's structured reason (e.g. X's CreditsDepleted /
        UsageCapExceeded payloads) without having to bump
        logging to DEBUG.
        """
        if self._transport is not None:
            return self._transport(url, access_token)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:  # noqa: BLE001
                err_body = ""
            logger.warning(
                "social search HTTP %s on %s: %s",
                e.code, url, err_body or "(no body)",
            )
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("social search transport failed: %s", e)
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("social search response not JSON: %s", e)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _normalise_response(
        self,
        body: dict[str, Any],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Vendor-specific → normalised mapping. The shape this
        method expects from the vendor is documented in
        ``docs/reference/social-routing.md`` and should be the
        only place that needs editing for a vendor format
        change.

        Expected vendor shape (the common modern social-search
        shape — adjust at build time):

          {
            "data": [
              {
                "id": "...",
                "text": "...",
                "author_id": "...",
                "created_at": "ISO timestamp",
                "public_metrics": {"like_count": ..., "retweet_count": ...},
                ...
              },
              ...
            ],
            "includes": {
              "users": [{"id": "...", "username": "..."}]
            }
          }

        ``id`` is used to build a vendor URL; ``author_id`` joins
        to the ``includes.users`` table. Vendors that send a
        ``url`` directly get it passed through.
        """
        items = body.get("data") or []
        if not isinstance(items, list):
            return []
        users_by_id: dict[str, str] = {}
        includes = body.get("includes")
        if isinstance(includes, dict):
            users = includes.get("users")
            if isinstance(users, list):
                for u in users:
                    if isinstance(u, dict):
                        uid = str(u.get("id", ""))
                        uname = str(u.get("username", "") or u.get("name", ""))
                        if uid:
                            users_by_id[uid] = uname

        cfg = self._cfg()
        url_template = getattr(
            cfg,
            "social_post_url_template",
            "",
        )

        out: list[dict[str, Any]] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            post_id = str(item.get("id", ""))
            text = str(item.get("text", item.get("content", "")) or "")
            author_id = str(item.get("author_id", ""))
            author = users_by_id.get(author_id, author_id) or "?"
            timestamp = str(item.get("created_at", item.get("timestamp", "")) or "")
            metrics = item.get("public_metrics") or item.get("metrics")
            url = item.get("url")
            if not url and url_template and post_id:
                url = url_template.format(
                    id=post_id,
                    author=author,
                    author_id=author_id,
                )
            normalised: dict[str, Any] = {
                "author": author,
                "text": text,
                "timestamp": timestamp,
                "url": url or "",
            }
            if isinstance(metrics, dict):
                normalised["metrics"] = metrics
            out.append(normalised)
        return out


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _read_bearer_token(cfg: Any) -> str | None:
    """Read the app-only bearer token from the configured path.

    The path lives in ``cfg.social_bearer_token_path``. The file
    is expected to contain just the token (no quoting, no JSON
    wrapping, no Bearer prefix); trailing whitespace / newlines
    are stripped.

    Returns ``None`` (silently) when:
      - the cfg field is unset or empty
      - the file doesn't exist
      - the file is empty / whitespace-only
      - the file isn't readable (OSError)

    Never raises into the caller — the search tool's graceful-
    degradation path expects None-or-token semantics.

    Security note: this function is the only place that touches
    token-shaped bytes outside the OAuth adapter. It does NOT
    log the token (length-only at DEBUG so an operator can
    confirm "the file was read" without leaking material). The
    return value flows into an Authorization header in
    :meth:`SocialProvider._get` and otherwise never appears in
    a string formatter.
    """
    path = getattr(cfg, "social_bearer_token_path", None)
    if not path:
        return None
    from pathlib import Path

    p = Path(str(path)).expanduser()
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(
            "social bearer token unreadable at %s: %s", p, e
        )
        return None
    tok = raw.strip()
    if not tok:
        return None
    logger.debug(
        "social bearer token loaded from %s (len=%d)", p, len(tok)
    )
    return tok
