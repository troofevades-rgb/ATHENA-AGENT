"""ContextVar-scoped approval grants.

Approvals granted in a foreground context must not bleed into
background forks (Phase 3 background_review) or curator runs (Phase
4). The approval guard installs a ``contextvars.ContextVar`` barrier
at every fork boundary: inside the fork the grant cache is empty,
and any code that calls :func:`request_approval` from background
either auto-approves (if explicitly opted in for that resource) or
raises :class:`ApprovalDeniedInBackground`.

This composes with — does not replace — the toolset restriction
model from Phase 0. Even if a background fork has access to a tool
that would normally prompt for approval in foreground, the prompt is
auto-denied in background unless the relevant resource carries
``auto_approve_in_background=True``.
"""
from __future__ import annotations

import contextvars
from typing import Awaitable, Callable

from ..provenance import FOREGROUND, get_current_write_origin


_approval_grants: contextvars.ContextVar[dict[str, bool]] = contextvars.ContextVar(
    "athena_approval_grants", default={},
)


class ApprovalDeniedInBackground(PermissionError):
    """Raised when a background context attempts an action that
    requires foreground approval, and the target resource has no
    ``auto_approve_in_background`` marker.
    """


async def request_approval(
    resource_id: str,
    prompt: Callable[[str], Awaitable[bool]],
    *,
    auto_approve_in_background: bool = False,
) -> bool:
    """Request approval for an action on ``resource_id``.

    In foreground: calls ``prompt(resource_id)``, caches the boolean
    result keyed by ``resource_id`` for the duration of the current
    ContextVar scope, and returns it.

    In background: returns True immediately if
    ``auto_approve_in_background`` is set; otherwise raises
    :class:`ApprovalDeniedInBackground`. The prompt callback is
    never invoked from background, even if a cached grant exists —
    the cache is per-context and a fresh fork has an empty cache by
    construction (see :func:`scope_fresh_approvals`).
    """
    origin = get_current_write_origin() or FOREGROUND
    grants = _approval_grants.get()

    if origin == FOREGROUND and resource_id in grants:
        return grants[resource_id]

    if origin != FOREGROUND:
        if auto_approve_in_background:
            return True
        raise ApprovalDeniedInBackground(
            f"action on {resource_id!r} requires foreground approval "
            f"(write_origin={origin!r})"
        )

    granted = await prompt(resource_id)
    # Copy-on-write so concurrent contexts can't observe a partially
    # mutated dict. ContextVar.set rebinds, it does not mutate.
    new_grants = dict(grants)
    new_grants[resource_id] = granted
    _approval_grants.set(new_grants)
    return granted


def scope_fresh_approvals() -> contextvars.Token[dict[str, bool]]:
    """Reset the approval grant cache for the current context.

    Called by :meth:`athena.agent.Agent.fork` before any tool calls
    in the fork. Pass the returned token to :func:`reset_approvals`
    in a finally block to restore the parent's grant cache.
    """
    return _approval_grants.set({})


def reset_approvals(token: contextvars.Token[dict[str, bool]]) -> None:
    """Restore the grant cache from the token returned by
    :func:`scope_fresh_approvals`."""
    _approval_grants.reset(token)


def current_grants() -> dict[str, bool]:
    """Read-only snapshot of the current grant cache. Returns a copy
    so callers can't mutate the live ContextVar value."""
    return dict(_approval_grants.get())
