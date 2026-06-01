"""Regression: a crashed TUI child must not hang the REPL.

The Ink subprocess can die after the protocol handshake (the
canonical case on Windows: ``setRawMode`` throws "Raw mode is not
supported" because the spawned Node's stdin isn't a TTY). When that
happens the reader loop sees socket EOF and signals ``_conn_died``,
deliberately NOT putting ``None`` on ``_cmd_queue`` — the reconnect
design expects a new client to dial back in.

But in the embedded REPL there is no supervisor to respawn the
child, so no reconnect can ever arrive. Before the fix, the accept
loop blocked in ``accept()`` forever and ``recv_command`` blocked
forever too: the user saw the boot banner and then "it just sits
there." The fix: when the spawned child has exited, the accept loop
flags ``_child_crashed`` and unblocks the REPL with ``None`` so it
can exit cleanly and surface the captured stderr.
"""

from __future__ import annotations

import threading
import time

from athena.tui_gateway.server import TuiGateway


class _DeadProc:
    """Minimal subprocess.Popen stand-in that reports it has exited."""

    def __init__(self, returncode: int = 1) -> None:
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode


class _LiveProc:
    """Stand-in that reports it is still running (poll() -> None)."""

    returncode = None

    def poll(self) -> None:
        return None


def _run_accept_loop_once(gateway: TuiGateway) -> threading.Thread:
    t = threading.Thread(target=gateway._accept_loop, daemon=True)
    t.start()
    return t


def test_dead_child_unblocks_recv_command_with_none() -> None:
    """A dead spawned child → accept loop flags the crash and puts
    None on the queue so ``recv_command`` returns instead of hanging."""
    gw = TuiGateway()
    gw._proc = _DeadProc(returncode=3)  # type: ignore[assignment]
    gw._conn = None
    gw._conn_reader = None

    t = _run_accept_loop_once(gw)
    # Simulate the reader seeing socket EOF after the child crashed.
    gw._conn_died.set()

    # recv_command must return None promptly (the bug was an infinite
    # block here).
    cmd = gw.recv_command(timeout=2.0)
    assert cmd is None
    assert gw._child_crashed is True

    gw._accept_stop.set()
    gw._conn_died.set()
    t.join(timeout=2.0)
    assert not t.is_alive()


def test_live_child_does_not_flag_crash() -> None:
    """If the child is still alive when the conn blips, the reconnect
    path stays in play — we must NOT declare a crash or unblock the
    REPL. The accept loop proceeds to wait for a reconnect (which we
    preempt via _accept_stop)."""
    gw = TuiGateway()
    gw._proc = _LiveProc()  # type: ignore[assignment]
    gw._conn = None
    gw._conn_reader = None

    # Make accept() return quickly with shutdown so the loop doesn't
    # block on a real socket: setting _accept_stop after _conn_died
    # drives it into the re-accept wait, which checks _accept_stop.
    t = _run_accept_loop_once(gw)
    gw._conn_died.set()
    # Give the loop a moment to process the death + enter accept-wait.
    time.sleep(0.2)

    # No crash was declared (child is alive → reconnect expected).
    assert gw._child_crashed is False
    # And recv_command did NOT get a None (nothing was queued).
    cmd = gw.recv_command(timeout=0.2)
    assert cmd is None  # timed out, not a queued sentinel
    assert gw._child_crashed is False

    gw._accept_stop.set()
    gw._conn_died.set()
    t.join(timeout=2.0)
