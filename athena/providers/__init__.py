"""Provider abstraction (Phase 8).

The agent talks to one or more model backends through a uniform
:class:`Provider` interface. Each backend (Ollama, Anthropic, OpenAI,
Google, OpenRouter, Nous, generic OpenAI-compat) is a subclass that
registers itself via :func:`register_provider`. A model name (plus
optional config routing) is resolved to a provider instance at agent
startup by :func:`runtime_resolver.resolve_provider` (added in
Prompt 8.6).

Importing :mod:`athena.providers` registers every built-in provider as a
side effect so the registry is fully populated by the time the agent
asks for one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Capabilities, Provider, StreamChunk

if TYPE_CHECKING:
    pass


# Name → Provider class. Populated by ``@register_provider`` at import time.
_REGISTRY: dict[str, type[Provider]] = {}


def register_provider(cls: type[Provider]) -> type[Provider]:
    """Class decorator. Registers ``cls`` under its ``name`` attribute.

    Re-registration is allowed (overwrites) so tests can swap a fake
    provider class in and out without monkey-patching the dict.
    """
    if not cls.name:
        raise ValueError(f"Provider {cls.__name__} must set a non-empty `name` attribute")
    _REGISTRY[cls.name] = cls
    return cls


def get_provider_class(name: str) -> type[Provider]:
    """Return the :class:`Provider` subclass registered under ``name``.

    Raises ``KeyError`` with a helpful message listing available names —
    typos at config time should be cheap to diagnose.
    """
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"unknown provider {name!r}. Available providers: {available}")
    return _REGISTRY[name]


def list_providers() -> list[str]:
    """Names of every registered provider, sorted."""
    return sorted(_REGISTRY)


def unregister(name: str) -> None:
    """Drop ``name`` from the registry. No-op if absent. Test affordance."""
    _REGISTRY.pop(name, None)


# ---------------------------------------------------------------------------
# Capability queries over _REGISTRY (T5-01R.4)
# ---------------------------------------------------------------------------


def capability_matrix() -> dict[str, Capabilities]:
    """``{provider_name: static_capabilities()}`` for every
    registered provider. Pure class-level introspection — no
    instances, no network. Suitable for ``athena providers``
    rendering and for downstream consumers (T5-05 broker, T5-06
    cache routing)."""
    return {name: cls.static_capabilities() for name, cls in _REGISTRY.items()}


def providers_with_capability(capability: str) -> list[str]:
    """Names of providers whose class-level manifest declares
    ``capability``. Sorted for stable output. Class-level only —
    "who *can* do X". Use
    :func:`runtime_resolver.available_providers_with_capability`
    when credential availability also matters."""
    return sorted(
        name for name, cls in _REGISTRY.items() if cls.static_capabilities().supports(capability)
    )


def best_provider_for(needs: set[str], prefer: str | None = None) -> str | None:
    """First provider whose class-level manifest covers every
    capability in ``needs``.

    ``prefer`` wins if it qualifies — downstream phases use this
    to express "I want Anthropic if it works, anything else with
    these capabilities otherwise." Returns ``None`` when no
    registered provider covers ``needs``. Candidates are
    alphabetised for deterministic fallback.
    """
    candidates = sorted(
        name
        for name, cls in _REGISTRY.items()
        if all(cls.static_capabilities().supports(n) for n in needs)
    )
    if not candidates:
        return None
    if prefer and prefer in candidates:
        return prefer
    return candidates[0]


__all__ = [
    "Capabilities",
    "Provider",
    "StreamChunk",
    "best_provider_for",
    "capability_matrix",
    "get_provider_class",
    "list_providers",
    "providers_with_capability",
    "register_provider",
    "unregister",
]


# Side-effect imports: each module's ``@register_provider`` decorator runs
# at import time so the registry is fully populated by the time anyone
# calls ``get_provider_class``. Order doesn't matter — registration is
# idempotent and keyed by ``name``.
from . import anthropic as _anthropic  # noqa: E402,F401
from . import google as _google  # noqa: E402,F401
from . import nous as _nous  # noqa: E402,F401
from . import ollama as _ollama  # noqa: E402,F401
from . import openai as _openai  # noqa: E402,F401
from . import openai_compat as _openai_compat  # noqa: E402,F401
from . import openrouter as _openrouter  # noqa: E402,F401
from . import social as _social  # noqa: E402,F401
