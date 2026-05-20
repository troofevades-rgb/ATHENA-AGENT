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
        graceful-when-absent path consult."""
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
        try:
            access_token = self._get_oauth().access_token()
        except Exception as e:  # noqa: BLE001
            logger.warning("social search: no token available: %s", e)
            return []

        cfg = self._cfg()
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
        """HTTP GET with the OAuth bearer token. Returns the parsed
        JSON body, or None on transport / decode failure.
        Injectable transport for tests (cfg-aware fallback to
        ``urllib`` in production)."""
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
