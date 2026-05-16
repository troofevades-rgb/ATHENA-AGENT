"""Per-fork provider construction.

A fork that shares the parent's HTTP client (1) competes for
connection-pool slots and (2) invalidates the parent's KV cache on most
providers. So forks default to building their own provider instance,
configured identically to the parent's.

Phase 8 still only constructs an :class:`OllamaProvider` here — Prompt
8.6 will replace this with the runtime resolver so forks of an
Anthropic / OpenAI / etc. parent get the matching provider class.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..providers.ollama import OllamaProvider

if TYPE_CHECKING:
    from .core import Agent
    from ..providers.base import Provider


def build_auxiliary_client(parent_agent: "Agent") -> "Provider":
    """Return a fresh provider configured identically to ``parent_agent``'s.

    Inspects the parent's runtime config (currently just
    ``cfg.ollama_host``) and constructs the parallel client. Phase 8.6
    swaps this body for ``runtime_resolver.resolve_provider`` so the
    fork's provider matches the parent's actual backend.
    """
    return OllamaProvider(parent_agent.cfg.ollama_host)
