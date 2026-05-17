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

from .base import Provider, StreamChunk

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
        raise ValueError(
            f"Provider {cls.__name__} must set a non-empty `name` attribute"
        )
    _REGISTRY[cls.name] = cls
    return cls


def get_provider_class(name: str) -> type[Provider]:
    """Return the :class:`Provider` subclass registered under ``name``.

    Raises ``KeyError`` with a helpful message listing available names —
    typos at config time should be cheap to diagnose.
    """
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(
            f"unknown provider {name!r}. Available providers: {available}"
        )
    return _REGISTRY[name]


def list_providers() -> list[str]:
    """Names of every registered provider, sorted."""
    return sorted(_REGISTRY)


def unregister(name: str) -> None:
    """Drop ``name`` from the registry. No-op if absent. Test affordance."""
    _REGISTRY.pop(name, None)


__all__ = [
    "Provider",
    "StreamChunk",
    "register_provider",
    "get_provider_class",
    "list_providers",
    "unregister",
]


# Side-effect imports: each module's ``@register_provider`` decorator runs
# at import time so the registry is fully populated by the time anyone
# calls ``get_provider_class``. Order doesn't matter — registration is
# idempotent and keyed by ``name``.
from . import ollama as _ollama  # noqa: E402,F401
from . import anthropic as _anthropic  # noqa: E402,F401
from . import openai as _openai  # noqa: E402,F401
from . import google as _google  # noqa: E402,F401
from . import openai_compat as _openai_compat  # noqa: E402,F401
from . import openrouter as _openrouter  # noqa: E402,F401
from . import nous as _nous  # noqa: E402,F401
