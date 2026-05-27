"""Interrupt-command side-channel dispatch.

ESC in the Ink TUI ships an ``InterruptCommand`` to the gateway.
The REPL is blocked inside ``agent.run_turn`` at that moment, so
queueing the command for the next ``recv_command()`` call would
never fire — the agent would have to finish naturally first, by
which point the interrupt is pointless.

The fix: the reader thread treats ``InterruptCommand`` like
``ConfirmReplyCommand`` — bypass the queue, dispatch immediately.
Specifically, call ``_thread.interrupt_main()`` to raise
``KeyboardInterrupt`` on the main thread at the next bytecode
boundary. The agent's tool dispatch / LLM call unwinds and the
existing ``except KeyboardInterrupt`` in the REPL catches it.

These tests pin that:
  1. Interrupts do NOT land on the cmd queue (would defeat their purpose)
  2. interrupt_main IS called when an interrupt frame arrives
  3. Other command types still queue normally (regression guard)
"""

from __future__ import annotations

import threading
import time

import pytest

from athena.tui_gateway import server as srv_mod
from athena.tui_gateway.events import (
    ConfirmReplyCommand,
    InterruptCommand,
    UserInputCommand,
)


class _FakeReader:
    """Stand-in for the gateway's BufferedReader. Yields a fixed
    sequence of JSON-RPC frames, then EOF."""

    def __init__(self, frames: list[bytes]) -> None:
        self._frames = list(frames)

    def readline(self) -> bytes:
        if not self._frames:
            return b""
        return self._frames.pop(0)


def _make_gateway_stub(frames: list[bytes]):
    """Build the minimum gateway surface ``_read_loop`` reads from.

    We don't instantiate the full TuiGateway (that spawns the TUI
    subprocess). Instead we satisfy the attribute access pattern of
    ``_read_loop`` with simple stand-ins.
    """
    import queue as _queue

    class _Stub:
        pass

    g = _Stub()
    g._conn_reader = _FakeReader(frames)
    g._cmd_queue = _queue.Queue()
    g._conn_died = threading.Event()
    g._last_pong_at = 0.0
    # Bind the real method so it uses our stubs
    g._read_loop = srv_mod.TuiGateway._read_loop.__get__(g)
    g._parse_frame = srv_mod.TuiGateway._parse_frame.__get__(g)
    g._dispatch_confirm_reply = lambda cmd: None
    return g


def _frame(method: str, params: dict | None = None) -> bytes:
    """JSON-RPC notification frame as a single line."""
    import json
    obj: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        obj["params"] = params
    return (json.dumps(obj) + "\n").encode("utf-8")


def test_interrupt_does_not_land_on_cmd_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt frame must bypass the REPL queue entirely.
    Otherwise the queued interrupt would only fire AFTER the
    currently-running turn finishes — exactly when it's useless."""
    interrupt_main_calls = [0]
    monkeypatch.setattr(
        "_thread.interrupt_main",
        lambda: interrupt_main_calls.__setitem__(0, interrupt_main_calls[0] + 1),
    )

    g = _make_gateway_stub([_frame("interrupt")])
    g._read_loop()

    assert g._cmd_queue.empty(), (
        "InterruptCommand was queued — REPL will not see it until "
        "the in-flight turn finishes, defeating the whole purpose"
    )
    assert interrupt_main_calls[0] == 1, (
        f"interrupt_main was called {interrupt_main_calls[0]} times; "
        "expected exactly 1"
    )


def test_user_input_still_queues_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: non-interrupt commands must still flow
    through the queue as before."""
    monkeypatch.setattr("_thread.interrupt_main", lambda: None)

    g = _make_gateway_stub([_frame("user.input", {"text": "hello"})])
    g._read_loop()

    cmd = g._cmd_queue.get_nowait()
    assert isinstance(cmd, UserInputCommand)
    assert cmd.text == "hello"


def test_interrupt_after_user_input_does_not_block_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed-frame scenario: user.input then interrupt arrives. The
    user.input must be queued AND the interrupt must dispatch
    independently — they don't have to land in order."""
    interrupt_main_calls = [0]
    monkeypatch.setattr(
        "_thread.interrupt_main",
        lambda: interrupt_main_calls.__setitem__(0, interrupt_main_calls[0] + 1),
    )

    g = _make_gateway_stub([
        _frame("user.input", {"text": "first"}),
        _frame("interrupt"),
    ])
    g._read_loop()

    # user.input is on the queue
    cmd = g._cmd_queue.get_nowait()
    assert isinstance(cmd, UserInputCommand)
    # Interrupt was dispatched (not queued)
    assert g._cmd_queue.empty()
    assert interrupt_main_calls[0] == 1


def test_interrupt_main_runtime_error_falls_back_to_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some embedded contexts (Jupyter, certain WSGI servers) raise
    RuntimeError from ``_thread.interrupt_main`` because they
    monkey-patch the main thread. Must fall back to the queue so
    the request is at least observable to the REPL later."""
    def _boom() -> None:
        raise RuntimeError("can't signal main in this context")

    monkeypatch.setattr("_thread.interrupt_main", _boom)

    g = _make_gateway_stub([_frame("interrupt")])
    g._read_loop()

    # Fell back to the queue
    cmd = g._cmd_queue.get_nowait()
    assert isinstance(cmd, InterruptCommand)


def test_confirm_reply_still_bypasses_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-existing behavior we must not regress: ConfirmReplyCommand
    has its own side-channel and must not end up on the queue."""
    monkeypatch.setattr("_thread.interrupt_main", lambda: None)
    dispatched = [0]

    g = _make_gateway_stub([
        _frame("confirm.reply", {"request_id": "r1", "accepted": True}),
    ])
    # Override the no-op stub with a counter
    g._dispatch_confirm_reply = lambda cmd: dispatched.__setitem__(
        0, dispatched[0] + 1
    )
    g._read_loop()

    assert g._cmd_queue.empty()
    assert dispatched[0] == 1
