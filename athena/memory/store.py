"""Thin façade over the active :class:`MemoryProvider`.

This module is the profile-keyed entry point Phase 5 introduced. Existing
workspace-keyed callers continue to use the legacy functions in
:mod:`athena.memory` (the package ``__init__``); Phase 14 will migrate them
to this façade.

The active provider is picked from config:

    [memory]
    provider = "builtin_file"      # default
    plugins.<name>.<key> = ...     # per-provider options

For now ``builtin_file`` is the only registered provider; this stays a name
keyed look-up so plugins (Phase 5+) can register alternates with
:func:`register_provider`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .providers.base import MemoryEntry, MemoryProvider
from .providers.builtin_file import BuiltinFileProvider

_FACTORIES: dict[str, Callable[[], MemoryProvider]] = {
    "builtin_file": BuiltinFileProvider,
}


def register_provider(name: str, factory: Callable[[], MemoryProvider]) -> None:
    """Register an alternate MemoryProvider factory. Plugins call this on
    load to expose their provider under a stable name."""
    _FACTORIES[name] = factory


def get_provider(name: str = "builtin_file") -> MemoryProvider:
    """Return a freshly constructed provider instance.

    Raises ``KeyError`` with the available names listed when ``name`` is
    unknown — keeps typos cheap to diagnose.
    """
    if name not in _FACTORIES:
        available = ", ".join(sorted(_FACTORIES)) or "(none)"
        raise KeyError(f"unknown memory provider {name!r}. Available: {available}")
    return _FACTORIES[name]()


# ---- Profile-keyed convenience API --------------------------------------


def load_index(
    profile: str,
    *,
    workspace: Path | None = None,
    provider_name: str = "builtin_file",
) -> str | None:
    """Load the MEMORY.md index for ``profile``.

    ``workspace`` (R2 stage 1) selects a workspace-scoped sub-store --
    the agent's system-prompt build will pass its workspace here in
    stage 2. MCP server tools and the ``athena memory`` CLI leave it
    ``None`` (single store per profile)."""
    return get_provider(provider_name).load_index(profile, workspace=workspace)


def write_entry(
    profile: str,
    *,
    filename: str,
    name: str,
    description: str,
    type: str,
    body: str,
    write_origin: str,
    workspace: Path | None = None,
    provider_name: str = "builtin_file",
) -> Path:
    return get_provider(provider_name).write_entry(
        profile,
        filename=filename,
        name=name,
        description=description,
        type=type,
        body=body,
        write_origin=write_origin,
        workspace=workspace,
    )


def list_entries(
    profile: str,
    *,
    workspace: Path | None = None,
    provider_name: str = "builtin_file",
) -> list[MemoryEntry]:
    return get_provider(provider_name).list_entries(profile, workspace=workspace)


def read_entry(
    profile: str,
    name: str,
    *,
    workspace: Path | None = None,
    provider_name: str = "builtin_file",
) -> MemoryEntry | None:
    return get_provider(provider_name).read_entry(profile, name, workspace=workspace)


def delete_entry(
    profile: str,
    name: str,
    *,
    workspace: Path | None = None,
    provider_name: str = "builtin_file",
) -> bool:
    return get_provider(provider_name).delete_entry(profile, name, workspace=workspace)


def query(
    profile: str,
    *,
    query: str,
    k: int = 5,
    workspace: Path | None = None,
    provider_name: str = "builtin_file",
) -> list[MemoryEntry]:
    return get_provider(provider_name).query(
        profile, query=query, k=k, workspace=workspace
    )
