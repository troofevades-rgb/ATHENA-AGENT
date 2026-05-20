"""Decide which provider handles each incoming proxy request.

Routing order (highest priority first):

1. ``X-Athena-Provider`` HTTP header — explicit per-request override.
   Honored only if the named provider is in ``available_providers``;
   silently ignored otherwise so a client that sent a header for a
   provider the user hasn't set up doesn't hard-fail.
2. Model-name match against the per-provider catalogue
   (:data:`KNOWN_MODELS_PER_PROVIDER`). First provider whose
   catalogue claims the requested model wins.
3. Fall back to ``default_provider`` (typically
   ``cfg.proxy_default_provider``).

OpenRouter and Ollama keep empty catalogues — OpenRouter accepts any
``vendor/model`` string from its huge catalogue and Ollama serves
whatever's locally installed. Treat the empty list as "doesn't claim
specific models"; both providers are reachable only via the header
override or the default-provider fallback.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Per-provider lists are intentionally small — only the model names a
# third-party client is likely to ask for by exact string. The point
# of this table is name-based routing, not a complete model
# enumeration; for everything else the client either sends the
# provider header or hits the default.
KNOWN_MODELS_PER_PROVIDER: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
    ],
    "google": [
        "gemini-2.0-flash",
        "gemini-2.5-pro",
    ],
    "openrouter": [],
    "ollama": [],
}


class RouteError(ValueError):
    """Raised when no provider can serve the request and no fallback
    is available. The error message lists the providers that were
    considered so the user can correct their config."""


def route_request(
    *,
    requested_model: str,
    provider_header: str | None,
    default_provider: str,
    available_providers: list[str],
) -> tuple[str, str]:
    """Return ``(provider_name, resolved_model)`` for an incoming request.

    ``resolved_model`` equals ``requested_model`` in every case
    handled here. Returning it as a separate value leaves room for
    future model-alias mappings (e.g. ``claude-3.7-sonnet`` →
    ``claude-sonnet-4-6``) without changing the signature.
    """
    if provider_header:
        # Lower-case the header value to match the registered provider
        # names. HTTP headers are case-insensitive in transport but
        # the value is just a string — be lenient.
        normalised = provider_header.strip().lower()
        if normalised in available_providers:
            return normalised, requested_model
        logger.debug(
            "X-Athena-Provider=%r not in available providers %s; ignoring",
            provider_header,
            available_providers,
        )

    for provider, models in KNOWN_MODELS_PER_PROVIDER.items():
        if provider not in available_providers:
            continue
        if requested_model in models:
            return provider, requested_model

    if default_provider not in available_providers:
        raise RouteError(
            f"default provider {default_provider!r} not available; "
            f"available providers: {sorted(available_providers)}. "
            "Add credentials with `athena providers add-key <name> <key>`."
        )
    return default_provider, requested_model
