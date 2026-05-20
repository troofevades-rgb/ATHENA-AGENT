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

Once the primary provider name is decided, the resolver attempts to
construct it. If the primary has no credential available (a hosted
provider with an empty bucket OR every credential in 429 cooldown),
the resolver walks the configured fallback chain
``cfg.providers.<primary>.fallback = [...]`` in order, trying each
listed provider with the ORIGINAL model string. OpenRouter accepts
``vendor/model`` verbatim, so falling back from anthropic to
openrouter "just works"; the chain entry can also be a per-fallback
``{provider, model}`` dict for cases where the model string needs to
change too (e.g., falling back to ollama with a local model name).

The bare model name returned to the caller is the model with its
routing prefix stripped — except for ``openrouter``, where the
``vendor/model`` form is what OpenRouter actually expects on the wire.

Errors that aren't credential-related (missing openai_compat host,
unknown provider name) bubble up immediately — fallback is only for
credential exhaustion. The final error after every chain entry is
exhausted lists the providers attempted so the user can correct.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from . import get_provider_class, providers_with_capability
from .base import Provider
from .credential_pool import CredentialPool

if TYPE_CHECKING:
    from ..config import Config


logger = logging.getLogger(__name__)


_PREFIX_TO_PROVIDER: dict[str, str] = {
    "anthropic/": "anthropic",
    "openai/": "openai",
    "google/": "google",
    "openrouter/": "openrouter",
    "nous/": "nous",
}

# Providers whose prefix is just a routing hint and should be stripped
# off before the model name goes on the wire.
_STRIP_PREFIX_FOR: frozenset[str] = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "nous",
    }
)


class _CredentialUnavailable(RuntimeError):
    """Internal sentinel — raised by ``_build_provider`` when a hosted
    provider has no available credential. The resolver catches this to
    walk the fallback chain; bare ``RuntimeError`` (config errors,
    missing host, etc.) is NOT caught and bubbles up to the user.
    """


def _route(model: str, cfg: Config) -> str:
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
                return model[len(prefix) :]
        # google: "gemini-..." passes through as-is
    return model


def _build_provider(
    name: str, model: str, cfg: Config, pool: CredentialPool
) -> tuple[Provider, str]:
    """Construct the provider class registered under ``name`` for ``model``.

    Raises :class:`_CredentialUnavailable` (a RuntimeError subclass) when
    a hosted provider has no available credential — the resolver catches
    this to walk the fallback chain. Other ``RuntimeError`` (missing
    config, unknown provider) bubble up.
    """
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
                '    host = "http://localhost:8000"\n'
            )
        cred = pool.get(name)
        api_key = cred.key if cred is not None else None
        return cls(host=host, api_key=api_key), bare

    # Hosted providers: anthropic / openai / google / openrouter / nous.
    cred = pool.get(name)
    if cred is None and getattr(cls, "requires_api_key", True):
        raise _CredentialUnavailable(f"no credentials available for provider {name!r}")
    api_key = cred.key if cred is not None else None
    kwargs: dict = {"api_key": api_key}
    if "base_url" in provider_cfg:
        kwargs["base_url"] = provider_cfg["base_url"]
    return cls(**kwargs), bare


def _fallback_chain(primary: str, cfg: Config) -> list[tuple[str, str | None]]:
    """Parse the fallback config for ``primary`` into a list of
    ``(provider_name, model_override)`` pairs.

    Two accepted shapes per entry:

    - ``"openrouter"`` — string. Reuses the original model string.
    - ``{"provider": "ollama", "model": "qwen2.5-coder:14b"}`` — dict.
      Lets the user remap the model string when the fallback provider
      can't address the primary's model directly.

    Unknown / malformed entries are dropped with a logged warning so a
    typo in one entry doesn't disable the whole chain.
    """
    raw = (cfg.providers or {}).get(primary, {}).get("fallback") or []
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str | None]] = []
    for entry in raw:
        if isinstance(entry, str) and entry:
            out.append((entry, None))
        elif isinstance(entry, dict) and isinstance(entry.get("provider"), str):
            out.append((entry["provider"], entry.get("model")))
        else:
            logger.warning(
                "providers.%s.fallback: unexpected entry %r — skipping",
                primary,
                entry,
            )
    return out


def available_providers_with_capability(
    capability: str,
    *,
    cfg: Config,
    pool: CredentialPool,
) -> list[str]:
    """Providers that BOTH declare ``capability`` AND are usable
    right now (T5-01R.4).

    "Usable" mirrors the credential gate in :func:`_build_provider`:

    - ``requires_api_key=False`` (Ollama, OpenAI-compat) — always
      usable; openai_compat additionally needs a configured host
      to actually serve, but that's a different surface from
      capability declaration.
    - Hosted providers — usable iff the credential pool has a
      live, non-cooldown credential.

    Returns sorted names so the broker's fallback chain is
    deterministic across runs.
    """
    out: list[str] = []
    for name in providers_with_capability(capability):
        cls = get_provider_class(name)
        if not getattr(cls, "requires_api_key", True):
            out.append(name)
            continue
        if pool.get(name) is not None:
            out.append(name)
    return sorted(out)


def resolve_provider(model: str, cfg: Config, pool: CredentialPool) -> tuple[Provider, str]:
    """Return a ``(Provider, bare_model)`` for ``model``.

    Walks the fallback chain when the primary's credentials are
    unavailable. The final ``RuntimeError`` on full exhaustion names
    every provider that was attempted.
    """
    primary = _route(model, cfg)
    attempts: list[tuple[str, str | None]] = [(primary, None)]
    attempts.extend(_fallback_chain(primary, cfg))

    tried: list[str] = []
    for name, model_override in attempts:
        effective_model = model_override if model_override is not None else model
        try:
            return _build_provider(name, effective_model, cfg, pool)
        except _CredentialUnavailable:
            tried.append(name)
            continue
        # Anything else: bubble up.

    # Every attempt exhausted on credentials.
    chain_str = " → ".join(tried)
    raise RuntimeError(
        f"no credentials available for provider {primary!r} "
        f"(also tried: {chain_str if len(tried) > 1 else 'no fallback configured'}). "
        f"Add one with:\n\n"
        f"    athena providers add-key {primary} <your-api-key>\n"
    )
