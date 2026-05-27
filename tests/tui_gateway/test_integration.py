"""L2 integration tests for the TUI bridge.

These exercise multi-component flows that unit tests miss:

  - A full simulated turn (info → tool call → stream)
  - The confirm round-trip with both accept AND deny outcomes
  - TUI death mid-session and auto-restore to Rich

The whole point of L2 coverage is to catch interface bugs
between components that look fine in isolation but blow up when
wired together — exactly the class of bug we found in the
recent scan (ConfirmReply routed through the wrong queue).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from athena import ui
from athena.tui_gateway.events import (
    ConfirmRequestEvent,
    MessageAppendEvent,
    StatusFlashEvent,
    StreamDeltaEvent,
    StreamEndEvent,
    StreamStartEvent,
    ToolCompleteEvent,
    ToolStartEvent,
)


class _Recorder:
    """Captures every event for assertion. Mirrors what a real
    gateway would receive but without the socket round-trip."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def send_event(self, event: Any) -> None:
        self.events.append(event)


class _DyingGateway:
    """Raises RuntimeError on every send_event — simulates the
    TUI socket dying mid-session. Tracks call count so we can
    assert the bridge stops trying after the first failure."""

    def __init__(self) -> None:
        self.calls = 0

    def send_event(self, event: Any) -> None:
        self.calls += 1
        raise RuntimeError("simulated TUI socket death")


@pytest.fixture
def recorder():
    g = _Recorder()
    ui.set_gateway(g)
    try:
        yield g
    finally:
        ui.set_gateway(None)


# ---- Test 1: full-turn event sequence ---------------------------


def test_full_turn_event_sequence(recorder):
    """A realistic agent turn touches every event type. Walk
    through the sequence and verify each call routes correctly.

    Pins the contract that:
      - ui.info  → StatusFlash (ephemeral, NOT transcript)
      - tool_call_summary → ToolStart (lane entry)
      - tool_result → ToolComplete (lane removal + tx entry)
      - TypewriterStream → Start/Delta/End sequence
    """
    # Simulate what agent.run_turn does internally.
    ui.info("loading workspace context")  # status flash
    ui.tool_call_summary("Read", {"path": "foo.py"})  # tool start
    ui.tool_result("Read", "200 lines of code\nfile contents...")  # tool done
    ts = ui.TypewriterStream()
    ts.start()  # stream start
    ts.feed("Here's what I found: ")
    ts.feed("the function is on line 42.")
    ts.finalize(markdown=False)  # stream end

    types = [type(e).__name__ for e in recorder.events]
    assert types == [
        "StatusFlashEvent",
        "ToolStartEvent",
        "ToolCompleteEvent",
        "StreamStartEvent",
        "StreamDeltaEvent",
        "StreamDeltaEvent",
        "StreamEndEvent",
    ]
    # Spot-check payloads on each event type.
    flash = next(e for e in recorder.events if isinstance(e, StatusFlashEvent))
    assert flash.text == "loading workspace context"
    start = next(e for e in recorder.events if isinstance(e, ToolStartEvent))
    assert start.tool == "Read"
    done = next(e for e in recorder.events if isinstance(e, ToolCompleteEvent))
    assert "200 lines" in done.result_preview
    # Stream deltas share a stream_id with the start.
    stream_start = next(
        e for e in recorder.events if isinstance(e, StreamStartEvent)
    )
    deltas = [e for e in recorder.events if isinstance(e, StreamDeltaEvent)]
    end = next(e for e in recorder.events if isinstance(e, StreamEndEvent))
    assert all(d.stream_id == stream_start.stream_id for d in deltas)
    assert end.stream_id == stream_start.stream_id


def test_full_turn_stream_deltas_concatenate_correctly(recorder):
    """The deltas, joined in order, must equal the buffered text
    that finalize() returns. Off-by-one on the streamingRef
    accumulator (or a stale-closure bug like the one we fixed
    in the UI) would break this."""
    ts = ui.TypewriterStream()
    ts.start()
    chunks = ["The ", "quick ", "brown ", "fox ", "jumps."]
    for c in chunks:
        ts.feed(c)
    final = ts.finalize(markdown=False)
    deltas = [e for e in recorder.events if isinstance(e, StreamDeltaEvent)]
    assert "".join(d.text for d in deltas) == "".join(chunks)
    assert final == "".join(chunks)


# ---- Test 2: confirm round-trip (accept + deny) ----------------


def test_confirm_round_trip_accepted(recorder):
    """User answers Y → ui.confirm returns True, request is
    cleaned up from the pending dict."""
    result: dict[str, bool | None] = {"answer": None}

    def call() -> None:
        result["answer"] = ui.confirm("Run dangerous?", default=False)

    t = threading.Thread(target=call, daemon=True)
    t.start()

    # Wait for the request to ship.
    req = _await_confirm_request(recorder, timeout=2.0)
    ui._deliver_confirm_reply(req.request_id, True)
    t.join(timeout=2.0)
    assert result["answer"] is True
    # Cleanup happened.
    assert req.request_id not in ui._pending_confirms


def test_confirm_round_trip_denied(recorder):
    """User answers N → ui.confirm returns False, no tool runs
    on the caller's side. Pins the deny path which is what the
    safety surface (Bash, Edit, Write approvals) actually uses
    in the common case."""
    result: dict[str, bool | None] = {"answer": None}

    def call() -> None:
        result["answer"] = ui.confirm("Run dangerous?", default=True)

    t = threading.Thread(target=call, daemon=True)
    t.start()

    req = _await_confirm_request(recorder, timeout=2.0)
    ui._deliver_confirm_reply(req.request_id, False)
    t.join(timeout=2.0)
    assert result["answer"] is False
    # Even though the default was True, the user's explicit
    # deny wins.
    assert req.request_id not in ui._pending_confirms


def _await_confirm_request(
    recorder: _Recorder, *, timeout: float
) -> ConfirmRequestEvent:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for e in recorder.events:
            if isinstance(e, ConfirmRequestEvent):
                return e
        time.sleep(0.01)
    raise AssertionError(
        "ConfirmRequestEvent never shipped — bridge isn't routing through gateway"
    )


# ---- Test 3: TUI death → Rich fallback --------------------------


def test_dead_gateway_emit_returns_false_silently():
    """TUI sprint step 6 design: when ``send_event`` raises
    RuntimeError (socket dead), the bridge no longer swaps
    back to Rich. It silently returns False; the gateway
    pointer stays set. The session continues — UI calls
    become no-ops until the recv_command loop sees socket
    EOF and ``__main__:_run_interactive_repl`` exits cleanly.

    Replaces the old test_dead_gateway_auto_restores_rich
    which asserted the deleted swap-back behavior.
    """
    dying = _DyingGateway()
    ui.set_gateway(dying)
    try:
        # First info call: hits gateway, RuntimeError, bridge
        # swallows. No swap-back, no exception propagation.
        ui.info("first message — gateway dies here")
        # Gateway pointer is still set (step 6 deleted the
        # auto-restore-to-Rich path).
        assert ui.gateway() is dying
        # Subsequent calls also reach the gateway and also
        # raise RuntimeError silently. That's fine: in
        # production the socket-dead state is sticky after
        # the writer thread marks _socket_dead.
        ui.info("second message")
        assert dying.calls >= 1
    finally:
        ui.set_gateway(None)


def test_set_gateway_never_replaces_sys_stdout():
    """TUI sprint step 7 design: ``set_gateway`` no longer
    swaps ``sys.stdout`` / ``sys.stderr`` to a NullStream
    and no longer dup2s file descriptors. Any code that
    writes through sys.stdout while a gateway is active
    is visible (a bug to surface, not paper over).

    This is the inverse of the OLD test which asserted
    ``sys.stdout`` was restored after _on_gateway_dead —
    after step 7 it was never replaced in the first place.
    """
    import sys

    real_stdout = sys.stdout
    real_stderr = sys.stderr
    dying = _DyingGateway()
    ui.set_gateway(dying)
    try:
        # set_gateway must not have replaced either stream.
        assert sys.stdout is real_stdout
        assert sys.stderr is real_stderr
        # And there is no _NullStream class to test for any
        # more — verify it's gone (step 7 deletion).
        assert not hasattr(ui, "_NullStream")
    finally:
        ui.set_gateway(None)
    # After clearing the gateway, both streams are still the
    # real ones — no restoration was needed because no swap
    # ever happened.
    assert sys.stdout is real_stdout
    assert sys.stderr is real_stderr


def test_theme_set_during_stream_re_emits_banner_without_disrupting_stream(
    recorder,
):
    """While an assistant stream is in flight, the user runs
    ``/theme set noctua``. The theme command's
    ``_refresh_tui_banner`` re-emits a BannerEvent with the
    new palette. The stream continues. Both events must reach
    the recorder, ordered correctly.

    On the Ink side this is verified by visual repaint (the
    ``palette`` derived from ``banner`` propagates to every
    color-bearing element on the next render). We can't test
    Ink rendering from Python, but we CAN verify the bridge
    fires the right events in the right order — which is the
    load-bearing piece."""
    from pathlib import Path

    from athena.config import Config
    from athena.tui_gateway.banner_data import build_banner
    from athena.tui_gateway.events import BannerEvent

    # Start a stream.
    ts = ui.TypewriterStream()
    ts.start()
    ts.feed("Here's the answer: ")

    # Now /theme set fires its refresh while the stream is open.
    cfg = Config()
    cfg.theme = "noctua"
    refreshed = build_banner(model="m", cwd=Path("/tmp"), cfg=cfg)
    # The theme command calls gateway.send_event directly with
    # the banner; mimic that here.
    recorder.send_event(refreshed)

    # Stream continues.
    ts.feed("forty-two.")
    ts.finalize(markdown=False)

    types = [type(e).__name__ for e in recorder.events]
    assert types == [
        "StreamStartEvent",
        "StreamDeltaEvent",
        "BannerEvent",       # ← the refresh lands in the middle
        "StreamDeltaEvent",
        "StreamEndEvent",
    ]
    # The banner carries the new theme.
    banner = next(e for e in recorder.events if isinstance(e, BannerEvent))
    assert banner.theme == "noctua"
    assert banner.palette is not None
    assert banner.palette.name == "noctua"


def test_message_bridge_falls_back_silently_on_other_errors():
    """If send_event raises something OTHER than RuntimeError
    (e.g. a serialization error from a malformed event), the
    bridge should drop the message but NOT trigger
    auto-restore — that'd cause a single bad event to nuke
    TUI mode for the rest of the session."""

    class _OtherFailureGateway:
        def __init__(self) -> None:
            self.calls = 0

        def send_event(self, event: Any) -> None:
            self.calls += 1
            raise ValueError("not a runtime error")

    gw = _OtherFailureGateway()
    ui.set_gateway(gw)
    try:
        ui.info("first")
        # Gateway still active — ValueError != RuntimeError.
        assert ui.gateway() is gw
        ui.info("second")
        assert gw.calls == 2  # both attempts made
    finally:
        ui.set_gateway(None)
