"""No-op desktop backend (T6-04.3).

Always reports ``is_available=False`` + an empty supports list.
Selected when no platform-specific backend is usable; the
observe-only co-pilot path checks ``backend.is_available()`` and
surfaces "not available on this host" instead of crashing.

A useful stand-in for tests too — construction takes no args
and has no side effects.
"""

from __future__ import annotations

from typing import Optional

from ..contract import Action, ActionType, Screenshot


class NoOpBackend:
    """Backend that does nothing — for hosts with no usable
    platform backend and for tests that don't need a real one."""

    name: str = "noop"

    def is_available(self) -> bool:
        return False

    def supports(self) -> list[ActionType]:
        return []

    def screenshot(self) -> Screenshot:
        raise RuntimeError("noop backend cannot capture the screen")

    def active_app(self) -> Optional[str]:
        return None

    def accessibility_tree(self) -> Optional[dict]:
        return None

    def perform(self, action: Action) -> None:
        raise RuntimeError("noop backend cannot perform input")
