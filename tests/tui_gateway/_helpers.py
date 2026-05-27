"""Test helpers for tui_gateway tests.

`FakeTuiGateway` records every event for assertion without
spawning a real socket. Replaces the inline `_Recorder` /
`_DyingGateway` patterns scattered through the existing tests
(test_integration.py, test_bridge_contract.py) so new tests
share one set of fixtures.

Use::

    from tests.tui_gateway._helpers import FakeTuiGateway
    from athena import ui

    def test_my_thing(monkeypatch):
        gw = FakeTuiGateway()
        ui.set_gateway(gw)
        try:
            # ... agent code that emits events ...
            assert gw.event_types() == ["status.flash", "message.append"]
            flash = gw.events_of_type("status.flash")[0]
            assert flash.text == "ack"
        finally:
            ui.set_gateway(None)
"""

from __future__ import annotations

from typing import Any


class FakeTuiGateway:
    """Records every event the bridge ships, with helpers for
    assertion. Mirrors `TuiGateway`'s public surface enough that
    `ui.set_gateway(FakeTuiGateway())` works.
    """

    def __init__(self) -> None:
        self._events: list[Any] = []
        self._raise_on_send: Exception | None = None

    # ---- TuiGateway public surface --------------------------------

    def send_event(self, event: Any) -> None:
        if self._raise_on_send is not None:
            raise self._raise_on_send
        self._events.append(event)

    def close(self) -> None:
        """No-op — fake gateway has nothing to tear down."""

    # ---- assertion helpers ----------------------------------------

    @property
    def events(self) -> list[Any]:
        """All events received, in arrival order."""
        return list(self._events)

    def event_types(self) -> list[str]:
        """Just the discriminator strings, in order. Useful for
        sequence assertions like
        ``assert gw.event_types() == ["status.flash", "stream.start"]``.
        """
        return [getattr(e, "type", type(e).__name__) for e in self._events]

    def events_of_type(self, type_literal: str) -> list[Any]:
        """All events whose ``.type`` matches the literal."""
        return [
            e for e in self._events
            if getattr(e, "type", None) == type_literal
        ]

    def last_of_type(self, type_literal: str) -> Any | None:
        """The most-recent event of the given type, or None."""
        for e in reversed(self._events):
            if getattr(e, "type", None) == type_literal:
                return e
        return None

    def clear(self) -> None:
        """Reset the recorded events list."""
        self._events.clear()

    # ---- failure injection ----------------------------------------

    def fail_next_send_with(self, exc: Exception) -> None:
        """Make the NEXT (and subsequent) send_event calls raise
        ``exc`` instead of recording. Used to test the bridge\'s
        dead-gateway path."""
        self._raise_on_send = exc

    def stop_failing(self) -> None:
        self._raise_on_send = None


class DyingGateway(FakeTuiGateway):
    """Convenience: a gateway that always raises RuntimeError on
    send_event — covers the "gateway socket died" scenario without
    fail_next_send_with boilerplate."""

    def __init__(self, msg: str = "simulated dead socket") -> None:
        super().__init__()
        self.fail_next_send_with(RuntimeError(msg))
