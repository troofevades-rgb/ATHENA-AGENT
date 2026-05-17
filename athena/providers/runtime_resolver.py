"""Resolve a (Provider, bare-model-name) pair for a given model string.

Routing priority:

1. Explicit override in ``config.providers.routing[model_name]``.
2. Prefix rules:
   - ``anthropic/<m>``         → anthropic
   - ``openai/<m>``             → openai
   - ``google/<m>`` or ``gemini-...`` → google
   - ``openrouter/<m>``         → openrouter
   - ``nous/<m>``               → nous
3. ``<host:port>/<model>`` form → openai_compat (the leading segment
   parses as a host with a port).
4. Anything else                → ollama (default; local-first posture).

Once the provider name is decided, the resolver:

- For ``ollama``: pulls the host from ``cfg.providers.ollama.host`` or
  falls back to the legacy top-level ``cfg.ollama_host``.
- For ``openai_compat``: requires ``cfg.providers.openai_compat.host``
  to be set; raises a clear error otherwise. API key is optional
  (local servers).
- For everything hosted: pulls an API key from the credential pool.
  If no credential is available and the provider requires one, raises
  a helpful error mentioning ``athena providers add-key``.

The bare model name returned to the caller is the model with its
routing prefix stripped — except for ``openrouter``, where the
``vendor/model`` form is what OpenRouter actually expects on the wire.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import get_provider_class
from .base import Provider
from .credential_pool import CredentialPool

if TYPE_CHECKING:
    from ..config import Config


_PREFIX_TO_PROVIDER: dict[str, str] = {
    "anthropic/": "anthropic",
    "openai/": "openai",
    "google/": "google",
    "openrouter/": "openrouter",
    "nous/": "nous",
}

# Providers whose prefix is just a routing hint and should be stripped
# off before the model name goes on the wire.
_STRIP_PREFIX_FOR: frozenset[str] = frozenset({
    "anthropic", "openai", "google", "nous",
})


def _route(model: str, cfg: "Config") -> str:
    """Decide which provider serves ``model``. Pure dispatch — no
    network calls, no credential lookups."""
    routing = (cfg.providers or {}).get("routing") or {}
    if isinstance(routing, dict) and model in routing:
        explicit = routing[model]
        if isinstance(explicit, str) and explicit:
            return explicit

    for prefix, name in _PREFIX_TO_PROVIDER.items():
        if model.startswith(prefix):
            return name

    if model.startswith("gemini-"):
        return "google"

    # <host:port>/<model> form — the leading segment looks like a host.
    if "/" in model:
        head = model.split("/", 1)[0]
        if ":" in head and not head.startswith(("http:", "https:")):
            return "openai_compat"
        if head.startswith("http://") or head.startswith("https://"):
            return "openai_compat"

    return "ollama"


def _bare_model(provider_name: str, model: str) -> str:
    """Strip the routing prefix from ``model`` when the provider doesn't
    want it on the wire."""
    if provider_name in _STRIP_PREFIX_FOR:
        for prefix, name in _PREFIX_TO_PROVIDER.items():
            if name == provider_name and model.startswith(prefix):
                return model[len(prefix):]
        # google: "gemini-..." passes through as-is
    return model


def resolve_provider(
    model: str, cfg: "Config", pool: CredentialPool
) -> tuple[Provider, str]:
    """Return a ``(Provider, bare_model)`` for ``model``.

    Raises :class:`RuntimeError` with a user-readable message when the
    routing decision can't be honored (missing host for openai_compat,
    no credentials for a key-requiring provider, etc.). Callers catch
    that and either fall through to a configured fallback chain or
    surface the error to the user.
    """
    name = _route(model, cfg)
    bare = _bare_model(name, model)
    cls = get_provider_class(name)
    provider_cfg = (cfg.providers or {}).get(name, {}) or {}

    if name == "ollama":
        host = provider_cfg.get("host") or cfg.ollama_host
        return cls(host=host), bare

    if name == "openai_compat":
        host = provider_cfg.get("host")
        if not host:
            raise RuntimeError(
                "openai_compat provider requires a host. Set "
                "providers.openai_compat.host in config.toml, e.g.\n\n"
                "    [providers.openai_compat]\n"
                "    host = \"http://localhost:8000\"\n"
            )
        cred = pool.get(name)
        api_key = cred.key if cred is not None else None
        return cls(host=host, api_key=api_key), bare

    # Hosted providers: anthropic / openai / google / openrouter / nous.
    cred = pool.get(name)
    if cred is None and getattr(cls, "requires_api_key", True):
        raise RuntimeError(
            f"no credentials available for provider {name!r}. "
            f"Add one with:\n\n"
            f"    athena providers add-key {name} <your-api-key>\n"
        )
    api_key = cred.key if cred is not None else None
    kwargs: dict = {"api_key": api_key}
    # Allow overriding base_url per-provider in config (useful for
    # staging endpoints, proxies, EU regions for OpenAI/Anthropic).
    if "base_url" in provider_cfg:
        kwargs["base_url"] = provider_cfg["base_url"]
    return cls(**kwargs), bare
