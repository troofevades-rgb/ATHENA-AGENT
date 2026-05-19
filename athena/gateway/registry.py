"""In-process registry of running :class:`GatewayDaemon` instances.

The cron subsystem's delivery layer needs a way to reach a running
gateway without re-importing platform SDKs or constructing its own
daemon. Solution: every :meth:`GatewayDaemon.start` call inserts the
daemon into this module-level registry keyed by profile; :meth:`stop`
removes it.

Out-of-process discovery (e.g. a separate ``athena cron daemon``
process talking to a separate ``athena gateway run`` process) is out
of scope here — that requires Unix-socket or HTTP-localhost IPC and
lands in a later phase. For the common case (one process running both
gateway and cron), this registry is enough.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .daemon import GatewayDaemon

logger = logging.getLogger(__name__)


_active: dict[str, GatewayDaemon] = {}


def register(daemon: GatewayDaemon) -> None:
    """Record ``daemon`` as the active gateway for its profile.

    A second register call for the same profile overwrites the first
    — useful if a test (or a controlled restart) tears down and
    re-creates a daemon. A warning is logged so accidental
    double-registration is visible.
    """
    profile = daemon.cfg.profile or "default"
    if profile in _active and _active[profile] is not daemon:
        logger.warning(
            "gateway registry: replacing active daemon for profile %r",
            profile,
        )
    _active[profile] = daemon


def unregister(daemon: GatewayDaemon) -> None:
    """Remove ``daemon`` from the registry. Identity-checked so a
    stopped-then-restarted daemon doesn't accidentally wipe its
    successor's slot."""
    profile = daemon.cfg.profile or "default"
    if _active.get(profile) is daemon:
        _active.pop(profile, None)


def get(profile: str = "default") -> GatewayDaemon | None:
    """Return the active daemon for ``profile``, or ``None``."""
    return _active.get(profile)


def list_active() -> list[GatewayDaemon]:
    """Snapshot of every active daemon — useful for diagnostics."""
    return list(_active.values())


def _clear_for_tests() -> None:
    """Test-only: drop every entry. Production code should never call
    this — :meth:`GatewayDaemon.stop` cleans up properly."""
    _active.clear()
