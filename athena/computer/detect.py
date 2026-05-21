"""Desktop backend detection + auto-selection (T6-04.3).

Two responsibilities:

  1. :func:`select_backend(cfg)` — pick the right backend for
     the current host. ``cfg.computer_backend == "auto"`` (the
     default) detects by platform; explicit values force a
     specific backend or the no-op stub.

  2. :func:`available_backends()` — list every backend the
     host can plausibly run, for ``athena computer status``.

Backends are imported LAZILY so importing this module doesn't
pull platform-specific dependencies that aren't installed on
other hosts.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from .contract import DesktopBackend

logger = logging.getLogger(__name__)


def select_backend(cfg: Any) -> DesktopBackend:
    """Resolve the configured backend.

    Returns the chosen :class:`DesktopBackend`. Always returns
    *something* — never raises — so callers can downstream check
    ``backend.is_available()`` to decide whether the observe
    path is usable. A host with no usable backend falls through
    to :class:`NoOpBackend` which reports ``is_available=False``
    + an empty supports list.
    """
    pref = str(getattr(cfg, "computer_backend", "auto")).lower()

    if pref == "noop":
        return _noop()
    if pref == "windows":
        return _try_windows() or _noop()
    if pref == "macos":
        return _try_macos() or _noop()
    if pref == "linux":
        return _try_linux() or _noop()

    # auto: pick by platform, fall back to noop.
    if sys.platform == "win32":
        return _try_windows() or _noop()
    if sys.platform == "darwin":
        return _try_macos() or _noop()
    if sys.platform.startswith("linux"):
        return _try_linux() or _noop()
    logger.info(
        "computer: no backend for platform %r; falling back to noop",
        sys.platform,
    )
    return _noop()


def available_backends() -> list[dict[str, Any]]:
    """For ``athena computer status`` — every backend with its
    availability + supported actions. Reports without
    constructing anything heavy."""
    out: list[dict[str, Any]] = []
    for builder, name in (
        (_try_windows, "windows"),
        (_try_macos, "macos"),
        (_try_linux, "linux"),
    ):
        backend = builder()
        if backend is None:
            out.append({"name": name, "available": False, "supports": []})
        else:
            out.append(
                {
                    "name": backend.name,
                    "available": bool(backend.is_available()),
                    "supports": list(backend.supports()),
                }
            )
    # Always advertise the noop too — that's what users see when
    # nothing matches their platform.
    out.append({"name": "noop", "available": True, "supports": []})
    return out


# ---------------------------------------------------------------------------
# Lazy per-platform import
# ---------------------------------------------------------------------------


def _try_windows() -> DesktopBackend | None:
    try:
        from .backends.windows import WindowsBackend
    except Exception as e:  # noqa: BLE001
        logger.debug("computer: windows backend unavailable: %s", e)
        return None
    return WindowsBackend()


def _try_macos() -> DesktopBackend | None:
    try:
        from .backends.macos import MacOSBackend
    except Exception as e:  # noqa: BLE001
        logger.debug("computer: macos backend unavailable: %s", e)
        return None
    return MacOSBackend()


def _try_linux() -> DesktopBackend | None:
    try:
        from .backends.linux import LinuxBackend
    except Exception as e:  # noqa: BLE001
        logger.debug("computer: linux backend unavailable: %s", e)
        return None
    return LinuxBackend()


def _noop() -> DesktopBackend:
    from .backends.noop import NoOpBackend

    return NoOpBackend()
