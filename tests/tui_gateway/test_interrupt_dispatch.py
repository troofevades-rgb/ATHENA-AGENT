"""Interrupt-command side-channel dispatch.

ESC / Ctrl+C in the Ink TUI ships an ``InterruptCommand`` to the
gateway. Two cases the dispatch has to cover:

  IDLE: main thread is blocked in ``recv_command -> queue.get()``
        waiting for the next user prompt. Putting the command on
        the queue is the ONLY reliable wake-up on Windows --
        ``_thread.interrupt_main`` queues a KeyboardInterrupt for
        the next bytecode boundary, but a main thread parked in a
        C-level condition-var wait inside queue.get never reaches
        that boundary, so the signal sits indefinitely. Users saw
        this as "Ctrl+C does nothing at the prompt -- I have to
        kill the terminal."

  MID-TURN: main thread is inside ``agent.run_turn`` (possibly
        deep inside an LLM stream). The queue is useless here --
        nothing's draining it. ``_thread.interrupt_main`` raises
        KeyboardInterrupt at the next bytecode boundary, and
        cancel hooks close in-flight httpx clients so that
        boundary actually gets reached.

So the dispatch does ALL THREE: enqueue (idle wake-up) + interrupt
main (mid-turn unwind) + cancel hooks (unblock C-level waits).
The REPL's ``isinstance(cmd, InterruptCommand)`` handler in
__main__.py decides what to do with the queued cmd: at idle it
exits cleanly, in a turn it's a no-op (run_turn already caught
the KeyboardInterrupt).

These tests pin that:
  1. Interrupts ARE queued (so idle queue.get wakes up)
  2. interrupt_main IS called (so mid-turn KeyboardInterrupt fires)
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


def test_interrupt_enqueued_and_interrupts_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt frame must do BOTH: enqueue so an idle
    queue.get() wakes up (the only reliable Windows wake-up for a
    main thread parked in a C-level condition-var wait), AND call
    interrupt_main so a mid-turn run_turn unwinds via
    KeyboardInterrupt. The REPL decides which case applies."""
    interrupt_main_calls = [0]
    monkeypatch.setattr(
        "_thread.interrupt_main",
        lambda: interrupt_main_calls.__setitem__(0, interrupt_main_calls[0] + 1),
    )

    g = _make_gateway_stub([_frame("interrupt")])
    g._read_loop()

    # 1. Enqueued -- idle wake-up.
    cmd = g._cmd_queue.get_nowait()
    assert isinstance(cmd, InterruptCommand)
    # 2. interrupt_main called -- mid-turn unwind path.
    assert interrupt_main_calls[0] == 1, (
        f"interrupt_main was called {interrupt_main_calls[0]} times; expected exactly 1"
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


def test_interrupt_after_user_input_both_on_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed-frame scenario: user.input then interrupt arrives. Both
    land on the queue in order (FIFO) and interrupt_main also
    fires. The REPL drains the user.input first, runs the turn,
    then sees the interrupt and exits if still applicable."""
    interrupt_main_calls = [0]
    monkeypatch.setattr(
        "_thread.interrupt_main",
        lambda: interrupt_main_calls.__setitem__(0, interrupt_main_calls[0] + 1),
    )

    g = _make_gateway_stub(
        [
            _frame("user.input", {"text": "first"}),
            _frame("interrupt"),
        ]
    )
    g._read_loop()

    # Both on the queue in FIFO order.
    first = g._cmd_queue.get_nowait()
    assert isinstance(first, UserInputCommand)
    second = g._cmd_queue.get_nowait()
    assert isinstance(second, InterruptCommand)
    assert interrupt_main_calls[0] == 1


def test_interrupt_main_runtime_error_does_not_prevent_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some embedded contexts (Jupyter, certain WSGI servers) raise
    RuntimeError from ``_thread.interrupt_main`` because they
    monkey-patch the main thread. The queue.put fires unconditionally
    BEFORE interrupt_main so this case still produces a wake-up
    even when the signal can't fire."""

    def _boom() -> None:
        raise RuntimeError("can't signal main in this context")

    monkeypatch.setattr("_thread.interrupt_main", _boom)

    g = _make_gateway_stub([_frame("interrupt")])
    g._read_loop()

    # Enqueue happened regardless of the RuntimeError.
    cmd = g._cmd_queue.get_nowait()
    assert isinstance(cmd, InterruptCommand)


def test_confirm_reply_still_bypasses_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-existing behavior we must not regress: ConfirmReplyCommand
    has its own side-channel and must not end up on the queue."""
    monkeypatch.setattr("_thread.interrupt_main", lambda: None)
    dispatched = [0]

    g = _make_gateway_stub(
        [
            _frame("confirm.reply", {"request_id": "r1", "accepted": True}),
        ]
    )
    # Override the no-op stub with a counter
    g._dispatch_confirm_reply = lambda cmd: dispatched.__setitem__(0, dispatched[0] + 1)
    g._read_loop()

    assert g._cmd_queue.empty()
    assert dispatched[0] == 1
