"""ContextVar tracking the write provenance of the current tool-call context.

Every tool call in athena runs under a known "write origin": foreground (user
asked for it directly), background_review (per-turn review fork), curator
(skill-curator fork), migration (one-shot import), system (internal lifecycle
machinery).

Provenance is the foundation for: autonomous-mutation logging, snapshot
attribution, fork sandboxing, and observability. Set it at the boundary that
takes responsibility for the work; read it from anywhere that records who did
what.
"""

import contextvars
from typing import Final

FOREGROUND: Final = "foreground"
BACKGROUND_REVIEW: Final = "background_review"
CURATOR: Final = "curator"
MIGRATION: Final = "migration"
SYSTEM: Final = "system"

_WRITE_ORIGINS: Final = {FOREGROUND, BACKGROUND_REVIEW, CURATOR, MIGRATION, SYSTEM}

_write_origin: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ocode_write_origin", default=FOREGROUND
)


def set_current_write_origin(origin: str) -> contextvars.Token[str]:
    """Bind the active write origin to the current context.

    Returns a token the caller MUST pass to ``reset_current_write_origin`` in a
    finally block. Unknown origins raise ``ValueError``.
    """
    if origin not in _WRITE_ORIGINS:
        raise ValueError(f"unknown write_origin {origin!r}")
    return _write_origin.set(origin)


def reset_current_write_origin(token: contextvars.Token[str]) -> None:
    """Restore the prior write origin from a token returned by ``set_current_write_origin``."""
    _write_origin.reset(token)


def get_current_write_origin() -> str:
    """Return the write origin bound to the current context."""
    return _write_origin.get()


def is_background() -> bool:
    """True when the current context is a background review or curator fork."""
    return get_current_write_origin() in (BACKGROUND_REVIEW, CURATOR)
