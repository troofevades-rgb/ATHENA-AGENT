"""Per-fork provider construction.

A fork that shares the parent's HTTP client (1) competes for
connection-pool slots and (2) invalidates the parent's KV cache on most
providers. So forks default to building their own provider instance,
configured identically to the parent's.

Phase 8.6: routes through the resolver so a fork of an Anthropic /
OpenAI / etc. parent gets the matching provider class — not always
Ollama. Re-resolution is deterministic per (model, cfg), so the fork's
provider class matches the parent's; the credential is pulled fresh
from the shared pool which may rotate between parent and fork.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..providers.credential_pool import global_pool as _global_pool
from ..providers.runtime_resolver import resolve_provider

if TYPE_CHECKING:
    from .core import Agent
    from ..providers.base import Provider


def build_auxiliary_client(parent_agent: "Agent") -> "Provider":
    """Return a fresh provider configured identically to ``parent_agent``'s."""
    provider, _bare_model = resolve_provider(
        parent_agent.cfg.model, parent_agent.cfg, _global_pool(),
    )
    return provider
