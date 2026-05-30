"""``lookup_x_user`` tool — profile + timeline for a specific X user.

Chains two API calls:

  1. ``/2/users/by/username/:username`` → user ID + profile
  2. ``/2/users/:id/tweets`` → recent posts

Returns a structured JSON payload the model can reason over for
OSINT-style analysis: who is this person, what do they post about,
what positions do they take.

Like ``search_x``, this routes through the T5-01 capability
manifest — the primary chat model stays unchanged, the social
provider handles the sub-call.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .. import ui
from ..tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="lookup_x_user",
    aliases=["x_user_profile"],
    toolset="recall",
    description=(
        "Look up a specific X / Twitter user by username and retrieve "
        "their profile and timeline. Use when the user asks about "
        "a specific person's X account, wants to see what someone has "
        "been posting, or needs OSINT-style analysis of someone's "
        "public social presence. Returns the user's bio, account info, "
        "and their posts (author, text, timestamp, url, metrics). "
        "Supports pagination: set max_pages > 1 to walk deeper into "
        "history, or pass a pagination_token from a previous call to "
        "continue where you left off. To find the earliest posts, "
        "paginate until next_token is null. "
        "The username can be provided with or without the @ prefix."
    ),
    parameters={
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "X / Twitter username (with or without @).",
            },
            "max_results": {
                "type": "integer",
                "description": "Total posts to return across all pages (default 50).",
            },
            "max_pages": {
                "type": "integer",
                "description": (
                    "Max API pages to fetch (each page up to 100 tweets). "
                    "Use higher values to reach older posts. Default 1. "
                    "Set to 10+ to dig deep into a user's history."
                ),
            },
            "pagination_token": {
                "type": "string",
                "description": (
                    "Resume pagination from a previous call's next_token. "
                    "Pass this to continue fetching older posts."
                ),
            },
        },
        "required": ["username"],
    },
    parallel_safe=True,
)
def lookup_x_user(
    username: str = "",
    max_results: int | None = None,
    max_pages: int | None = None,
    pagination_token: str | None = None,
    **_kwargs: Any,
) -> str:
    if not username or not str(username).strip():
        return _payload(available=False, reason="empty username")

    username = str(username).lstrip("@").strip()
    provider_name, provider = _resolve_social_provider()
    if provider is None:
        return _payload(
            available=False,
            reason="no social-search provider configured",
        )

    ui.info(f"looking up @{username} via {provider_name}")
    logger.info("lookup_x_user: resolving username=%r via provider=%r", username, provider_name)

    try:
        profile = provider.user_lookup(username)
    except Exception as e:  # noqa: BLE001
        logger.warning("lookup_x_user: user_lookup raised: %s", e)
        return _payload(
            available=False,
            provider=provider_name,
            reason=f"user lookup failed: {e}",
        )

    if profile is None:
        return _payload(
            available=False,
            provider=provider_name,
            reason=f"user @{username} not found or lookup endpoint not configured",
        )

    user_id = str(profile.get("id", ""))
    if not user_id:
        return _payload(
            available=False,
            provider=provider_name,
            reason=f"user @{username} found but missing ID",
        )

    pages = int(max_pages) if max_pages else 1
    n = int(max_results) if max_results else None

    ui.info(f"fetching timeline for @{username} (id={user_id}, pages={pages})")

    try:
        posts, next_token = provider.user_timeline(
            user_id,
            max_results=n,
            max_pages=pages,
            pagination_token=pagination_token,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("lookup_x_user: user_timeline raised: %s", e)
        posts, next_token = [], None

    # The provider swallows HTTP errors (402/403/429) inside _get and
    # returns an empty page, so an empty timeline used to look identical
    # to a genuinely post-less account. Surface the real reason when the
    # timeline came back empty AND the provider recorded a transport
    # error — otherwise the model reports "no posts" for what is really
    # an access/credit/rate-limit problem.
    timeline_error = getattr(provider, "last_error", None)
    reason: str | None = None
    if not posts and timeline_error:
        reason = f"timeline fetch returned no posts — X API said: {timeline_error}"

    return _payload(
        available=True,
        provider=provider_name,
        profile=_normalise_profile(profile),
        posts=posts or [],
        next_token=next_token,
        reason=reason,
    )


def _resolve_social_provider() -> tuple[str | None, Any]:
    from ..providers import best_provider_for, get_provider_class

    name = best_provider_for({"social_search"})
    if name is None:
        return None, None
    cls = get_provider_class(name)
    try:
        instance = cls()
    except Exception as e:  # noqa: BLE001
        logger.warning("lookup_x_user: could not instantiate provider %r: %s", name, e)
        return name, None

    is_available_fn = getattr(instance, "is_available", None)
    if callable(is_available_fn):
        try:
            if not is_available_fn():
                return name, None
        except Exception:  # noqa: BLE001
            return name, None
    return name, instance


def _normalise_profile(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(raw.get("id", "")),
        "username": str(raw.get("username", "")),
        "name": str(raw.get("name", "")),
        "description": str(raw.get("description", "")),
    }
    for field in ("created_at", "location", "url", "verified", "profile_image_url"):
        val = raw.get(field)
        if val is not None:
            out[field] = val
    metrics = raw.get("public_metrics")
    if isinstance(metrics, dict):
        out["metrics"] = metrics
    return out


def _payload(
    *,
    available: bool,
    provider: str | None = None,
    profile: dict[str, Any] | None = None,
    posts: list[dict[str, Any]] | None = None,
    next_token: str | None = None,
    reason: str | None = None,
) -> str:
    body: dict[str, Any] = {
        "available": bool(available),
        "provider": provider,
        "profile": profile,
        "posts": list(posts or []),
        "reason": reason,
    }
    if next_token:
        body["next_token"] = next_token
    return json.dumps(body, ensure_ascii=False)
