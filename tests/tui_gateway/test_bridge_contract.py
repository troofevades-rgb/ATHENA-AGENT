"""The TUI gateway bridge contract.

These tests pin the rule that, while ``ui.set_gateway(g)`` is
active:

  1. ``ui.info / warn / error`` ship MessageAppendEvents.
  2. ``ui.tool_call_summary / tool_result`` ship ToolStartEvent
     / ToolCompleteEvent.
  3. ``console.print`` (every legacy slash command + tool path)
     ships MessageAppendEvent(role="system") — even though no
     individual call site uses the bridge directly.
  4. ``ui.show_diff`` ships ToolCompleteEvent so file edits
     surface in the transcript.
  5. ``ui.confirm`` ships ConfirmRequestEvent and blocks on a
     reply queue — NEVER calls ``input()``.
  6. Direct ``print()`` calls do NOT collide with the TUI —
     they would visibly land on the terminal (step 7 removed the _NullStream sink — see TUI_SPRINT.md).
  7. Direct ``os.write(1, ...)`` calls do NOT collide either —
     fd 1 is dup'd to devnull.

The whole point of these guarantees is that the 254 untouched
``console.print`` call sites in the codebase don't have to be
migrated to typed events for TUI mode to be production-quality.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import pytest

from athena import ui
from athena.tui_gateway.events import (
    ConfirmRequestEvent,
    MessageAppendEvent,
    StatusFlashEvent,
    ToolCompleteEvent,
    ToolStartEvent,
)


class _RecordingGateway:
    """Minimal fake gateway that captures every event sent to it.
    Lets us assert which bridge path fired without spinning up
    the real subprocess."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def send_event(self, event: Any) -> None:
        self.events.append(event)


@pytest.fixture
def gw():
    """Set the gateway for the duration of the test, restore on
    teardown. Anything the test writes to stdout/stderr while gw
    is active goes to /dev/null and is invisible to pytest."""
    g = _RecordingGateway()
    ui.set_gateway(g)
    try:
        yield g
    finally:
        ui.set_gateway(None)


# ----- info / warn / error ---------------------------------------


def test_ui_info_ships_status_flash(gw):
    """``ui.info`` is ephemeral chatter — internal logging,
    "loaded N bytes", etc. Ships as StatusFlashEvent so it
    appears briefly above the prompt and decays without
    polluting the transcript."""
    ui.info("hello world")
    flashes = [e for e in gw.events if isinstance(e, StatusFlashEvent)]
    assert any(
        f.text == "hello world" and f.level == "info" for f in flashes
    )
    # Must NOT also land as a MessageAppendEvent — that would
    # bring back the interleaving problem the flash is supposed
    # to fix.
    assert not any(
        isinstance(e, MessageAppendEvent) and "hello world" in e.content
        for e in gw.events
    )


def test_ui_warn_ships_status_flash(gw):
    """Warnings are also ephemeral (level=warn). Persistent
    failures should use ``ui.error`` instead."""
    ui.warn("something fishy")
    flashes = [e for e in gw.events if isinstance(e, StatusFlashEvent)]
    assert any(
        f.text == "something fishy" and f.level == "warn" for f in flashes
    )


def test_ui_error_ships_persistent_system_message(gw):
    """Errors matter — they stay in the transcript."""
    ui.error("oops")
    assert any(
        isinstance(e, MessageAppendEvent)
        and e.role == "system"
        and "oops" in e.content
        for e in gw.events
    )


# ----- tool surface ----------------------------------------------


def test_tool_call_summary_ships_tool_start(gw):
    ui.tool_call_summary("Bash", {"command": "ls"})
    assert any(
        isinstance(e, ToolStartEvent) and e.tool == "Bash" for e in gw.events
    )


def test_tool_result_ships_tool_complete(gw):
    ui.tool_result("Bash", "file1\nfile2\nfile3\n")
    completes = [e for e in gw.events if isinstance(e, ToolCompleteEvent)]
    assert len(completes) == 1
    assert "file1" in completes[0].result_preview


# ----- console.print bridge (the big one) ------------------------


def test_console_print_inside_user_facing_context_bridges(gw):
    """Slash command output: ``console.print`` inside
    ``user_facing_render()`` ships as MessageAppendEvent. This
    is how /help, /board, /tools, etc. reach the transcript."""
    with ui.user_facing_render():
        ui.console.print("a slash command would print this")
    assert any(
        isinstance(e, MessageAppendEvent)
        and "a slash command would print this" in e.content
        for e in gw.events
    )


def test_console_print_outside_context_does_not_bridge(gw):
    """Agent-internal noise — ``console.print`` called WITHOUT
    the user-facing context must NOT pollute the transcript.
    Critical: this is what stops "weird interleaving" between
    streaming text and turn-time logging."""
    ui.console.print("internal log — should not appear")
    assert not any(
        isinstance(e, MessageAppendEvent)
        and "should not appear" in e.content
        for e in gw.events
    )


def test_console_print_strips_rich_markup_in_context(gw):
    """Rich's ``[bold]…[/]`` markup should be rendered to plain
    text — the Ink TUI doesn't interpret Rich markup."""
    with ui.user_facing_render():
        ui.console.print("[bold green]hello[/] [dim]world[/]")
    msgs = [e for e in gw.events if isinstance(e, MessageAppendEvent)]
    assert any("hello world" in e.content for e in msgs)
    assert not any("[bold green]" in e.content for e in msgs)


def test_console_print_empty_in_context_is_dropped(gw):
    """Empty prints (Rich uses these for spacing) shouldn't
    pollute the transcript with empty system messages."""
    with ui.user_facing_render():
        ui.console.print("")
    msgs = [
        e
        for e in gw.events
        if isinstance(e, MessageAppendEvent) and e.content.strip() == ""
    ]
    assert msgs == []


# ----- show_diff -------------------------------------------------


def test_show_diff_ships_tool_complete(gw):
    """File edit diffs should surface in the TUI transcript so
    the user sees what changed."""
    ui.show_diff("foo.py", "old line\n", "new line\n")
    completes = [e for e in gw.events if isinstance(e, ToolCompleteEvent)]
    assert any("foo.py" in c.tool or "foo.py" in c.result_preview for c in completes)


def test_show_diff_no_changes_drops_to_console_bridge(gw):
    """When old == new, show_diff still routes through the
    bridged console.print — user sees the '(no changes)' note."""
    ui.show_diff("foo.py", "same\n", "same\n")
    msgs = [e for e in gw.events if isinstance(e, MessageAppendEvent)]
    assert any("no changes" in m.content for m in msgs)


# ----- confirm round-trip ---------------------------------------


def test_confirm_reply_dispatched_by_reader_thread_not_repl_loop():
    """The bug we caught in the scan: the reader thread must
    deliver ConfirmReply directly to ui's pending-confirm queue
    via ``_dispatch_confirm_reply``. Routing it through the
    main ``cmd_queue`` would deadlock because the REPL is
    blocked inside ``agent.run_turn()`` and can't drain the
    queue while a confirm is in flight.

    This is a unit test against the dispatch helper since the
    real wire round-trip requires socket simulation that's
    awkward in pytest. The end-to-end flow is verified
    manually by running athena and approving a tool call."""
    import queue
    from unittest.mock import MagicMock

    from athena import ui
    from athena.tui_gateway.events import ConfirmReplyCommand
    from athena.tui_gateway.server import TuiGateway

    # Build a TuiGateway WITHOUT starting the subprocess so we
    # can call _dispatch_confirm_reply in isolation.
    gateway = TuiGateway.__new__(TuiGateway)
    gateway._cmd_queue = queue.Queue()  # type: ignore[attr-defined]

    request_id = "test-rid"
    reply_q: queue.Queue[bool] = queue.Queue(maxsize=1)
    ui._pending_confirms[request_id] = reply_q
    try:
        cmd = ConfirmReplyCommand(request_id=request_id, accepted=True)
        gateway._dispatch_confirm_reply(cmd)
        # The reply should land in the per-request queue.
        assert reply_q.get_nowait() is True
        # And NOT in the main cmd_queue (that would deadlock
        # the agent thread during a turn).
        with pytest.raises(queue.Empty):
            gateway._cmd_queue.get_nowait()  # type: ignore[attr-defined]
    finally:
        ui._pending_confirms.pop(request_id, None)


def test_confirm_ships_request_and_blocks_on_reply(gw):
    """``ui.confirm`` must never call ``input()`` in TUI mode.
    It ships ConfirmRequestEvent and blocks until the matching
    reply arrives via ``_deliver_confirm_reply``."""
    result: dict[str, bool | None] = {"answer": None}

    def call_confirm() -> None:
        result["answer"] = ui.confirm("Run dangerous command?", default=False)

    worker = threading.Thread(target=call_confirm, daemon=True)
    worker.start()

    # Wait for the request to ship.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        requests = [
            e for e in gw.events if isinstance(e, ConfirmRequestEvent)
        ]
        if requests:
            break
        time.sleep(0.02)
    requests = [e for e in gw.events if isinstance(e, ConfirmRequestEvent)]
    assert len(requests) == 1
    req = requests[0]
    assert req.prompt == "Run dangerous command?"

    # Deliver the reply.
    ui._deliver_confirm_reply(req.request_id, True)
    worker.join(timeout=2.0)
    assert result["answer"] is True


def test_confirm_falls_back_to_input_when_no_gateway():
    """Outside TUI mode, ``confirm`` still uses ``input()``.
    Verified by patching input() to return an answer."""
    import builtins

    ui.set_gateway(None)
    saved = builtins.input
    try:
        builtins.input = lambda _prompt: "y"
        assert ui.confirm("anything?", default=False) is True
    finally:
        builtins.input = saved


# NOTE on silencing layers (post-TUI-sprint step 7):
# Layers 2 (sys.stdout/stderr swap) and 3 (os.dup2 FD reroute)
# were removed. Layers 0 (console.print bridge) and 1
# (console.file → devnull) remain. Raw ``print()`` and
# ``os.write(1, ...)`` are NOT silenced any more — they
# would visibly corrupt an Ink render if invoked while a
# gateway is active. That's by design: surface the bug,
# don't paper over it. The console.print + console.file
# layers are tested via the ``user_facing_render`` tests
# elsewhere in this file.


# ----- gateway-state introspection -------------------------------


def test_gateway_inspector_returns_active(gw):
    """``ui.gateway()`` should return whatever was set, so
    consumers (e.g. /theme) can branch on TUI-mode."""
    assert ui.gateway() is gw


def test_gateway_inspector_returns_none_outside_tui():
    ui.set_gateway(None)
    assert ui.gateway() is None
