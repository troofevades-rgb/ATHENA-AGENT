"""Step 4a handshake + heartbeat tests.

These exercise the gateway lifecycle without spawning Node. A
fake Python client connects to the gateway transport and
mimics what the Ink bundle does: receive HelloEvent, send
HelloCommand, reply to every PingEvent with a PongCommand.

Coverage:
  - Hello round-trip with protocol_version=2 succeeds
  - Server emits PingEvent on its cadence
  - Server consumes PongCommand and updates _last_pong_at
  - Every outbound event carries a monotonic ``seq`` field
  - Mismatched protocol_version raises _HandshakeError and
    emits a ProtocolErrorEvent with code='protocol_version_mismatch'

Added in TUI sprint step 4a.
"""

from __future__ import annotations

import io
import json
import queue
import socket
import sys
import threading
import time

import pytest

from athena.tui_gateway import server as srv
from athena.tui_gateway.events import MessageAppendEvent

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="uses UDS; Windows path runs the same logic via TCP fallback",
)


@pytest.fixture
def fast_heartbeats(monkeypatch):
    """Run the heartbeat loop at 50ms cadence so the test is quick."""
    monkeypatch.setattr(srv, "_PING_INTERVAL_S", 0.05)
    monkeypatch.setattr(srv, "_DEAD_TIMEOUT_S", 2.0)


def _build_stub_gateway(transport):
    """Build a TuiGateway with the supplied (already-bound)
    transport, bypassing __init__'s default transport
    construction. Intentionally minimal — just the fields
    start()/handshake/heartbeats touch."""
    gw = srv.TuiGateway.__new__(srv.TuiGateway)
    gw._transport = transport
    gw._proc = None
    gw._cmd_queue = queue.Queue()
    gw._reader_thread = None
    gw._write_lock = threading.Lock()
    gw._closed = False
    gw._conn = None
    gw._conn_reader = None
    gw._accept_timeout_s = 2.0
    gw._tty_passthrough = False
    gw._socket_dead = False
    gw._next_seq = 0
    gw._seq_lock = threading.Lock()
    gw._heartbeat_thread = None
    gw._heartbeat_stop = threading.Event()
    gw._last_pong_at = 0.0
    gw._handshake_done = False
    # Step 4b outbound writer machinery -- send_event reaches into all
    # of these. test_outbound_queue's stub already wires them up; this
    # stub originally predated the writer-thread split and worked on
    # Windows-host CI because send_event was never exercised by the
    # tests in this file, but ``test_heartbeat_and_seq_monotonic``
    # calls ``send_event`` directly. Linux CI surfaces the missing
    # attributes.
    gw._outbound = srv._OutboundQueue()
    gw._writer_thread = None
    gw._writer_stop = threading.Event()
    gw._conn_ready = threading.Event()
    gw._conn_died = threading.Event()
    gw._ring = srv._EventRing()
    return gw


def _spawn_client(
    sock_path, *, send_pong=True, pongs_target=3, protocol_version=2, drain_after_hello=0
):
    """Background thread that simulates the Ink client. Returns
    a dict you can read after thread.join() with what it saw.

    ``drain_after_hello`` reads that many frames right after sending the
    client hello, before the pong loop — needed when the server sends a
    frame (e.g. protocol.error on a version mismatch) and then closes,
    so ``pongs_target=0`` wouldn't otherwise read it."""
    state = {"events": [], "pongs": 0, "seqs": [], "err": None}

    def runner():
        try:
            c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            c.connect(sock_path)
            f = c.makefile("rwb", buffering=0)
            line = f.readline().decode("utf-8")
            server_hello = json.loads(line)
            state["events"].append(server_hello)
            f.write(
                (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "hello",
                            "params": {
                                "protocol_version": protocol_version,
                                "client_version": "fake-ink-test",
                                "capabilities": ["heartbeats", "seq"],
                                "last_seq": 0,
                            },
                        }
                    )
                    + chr(10)
                ).encode("utf-8")
            )
            f.flush()
            for _ in range(drain_after_hello):
                extra = f.readline()
                if not extra:
                    break
                state["events"].append(json.loads(extra.decode("utf-8")))
            while state["pongs"] < pongs_target:
                line = f.readline()
                if not line:
                    break
                msg = json.loads(line.decode("utf-8"))
                state["events"].append(msg)
                if "seq" in msg:
                    state["seqs"].append(msg["seq"])
                if msg.get("method") == "ping" and send_pong:
                    f.write(
                        (
                            json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "method": "pong",
                                    "params": {},
                                }
                            )
                            + chr(10)
                        ).encode("utf-8")
                    )
                    f.flush()
                    state["pongs"] += 1
            c.close()
        except BaseException as e:
            state["err"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t, state


def _drive_gateway_through_handshake(gw, transport):
    """Mirror what start() does AFTER spawning, without the spawn."""
    conn = transport.accept(timeout_s=2.0)
    gw._conn = conn
    gw._conn_reader = io.BufferedReader(socket.SocketIO(conn, "rb"))
    gw._do_handshake()
    gw._last_pong_at = time.monotonic()
    gw._handshake_done = True
    # start() marks the conn ready + spawns the writer right after a
    # successful handshake; mirror that so queued events/pings actually
    # ship. (_do_handshake raises on version mismatch, so this is skipped
    # there and the protocol.error goes out via the direct
    # _send_event_raw path inside _do_handshake.)
    gw._conn_ready.set()
    gw._writer_thread = threading.Thread(target=gw._writer_loop, daemon=True)
    gw._writer_thread.start()
    return conn


def test_hello_handshake_with_matching_version(fast_heartbeats):
    transport = srv._UnixDomainTransport()
    transport.bind()
    try:
        gw = _build_stub_gateway(transport)
        _, env_value = transport.env_var()
        client_t, state = _spawn_client(env_value, pongs_target=0)
        try:
            _drive_gateway_through_handshake(gw, transport)
        finally:
            client_t.join(timeout=2.0)
        assert state["err"] is None, state["err"]
        # The client saw the server's hello with our protocol_version.
        assert state["events"][0]["method"] == "hello"
        assert state["events"][0]["params"]["protocol_version"] == 2
        # _GATEWAY_CAPABILITIES in athena/tui_gateway/server.py grew
        # ``coalesce`` when outbound batching shipped; the test wasn't
        # updated then.
        assert state["events"][0]["params"]["capabilities"] == [
            "heartbeats",
            "seq",
            "coalesce",
        ]
    finally:
        transport.close()


def test_mismatched_protocol_version_raises(fast_heartbeats):
    transport = srv._UnixDomainTransport()
    transport.bind()
    try:
        gw = _build_stub_gateway(transport)
        _, env_value = transport.env_var()
        # Client claims protocol v999, server rejects.
        client_t, state = _spawn_client(
            env_value,
            pongs_target=0,
            protocol_version=999,
            drain_after_hello=1,  # read the protocol.error frame before EOF
        )
        try:
            with pytest.raises(srv._HandshakeError, match="version mismatch"):
                _drive_gateway_through_handshake(gw, transport)
        finally:
            client_t.join(timeout=2.0)
        # The client should have received a protocol.error before
        # the server closed.
        err_events = [e for e in state["events"] if e.get("method") == "protocol.error"]
        assert err_events, (
            f"client did not receive protocol.error event; "
            f"saw {[e.get('method') for e in state['events']]}"
        )
        assert err_events[0]["params"]["code"] == "protocol_version_mismatch"
    finally:
        transport.close()


def test_heartbeat_and_seq_monotonic(fast_heartbeats):
    transport = srv._UnixDomainTransport()
    transport.bind()
    try:
        gw = _build_stub_gateway(transport)
        _, env_value = transport.env_var()
        client_t, state = _spawn_client(env_value, pongs_target=3)
        try:
            _drive_gateway_through_handshake(gw, transport)
            # Spawn heartbeat + reader threads.
            gw._heartbeat_thread = threading.Thread(
                target=gw._heartbeat_loop,
                daemon=True,
            )
            gw._heartbeat_thread.start()
            gw._reader_thread = threading.Thread(
                target=gw._read_loop,
                daemon=True,
            )
            gw._reader_thread.start()
            # Send a real event so seq=1 is exercised.
            gw.send_event(MessageAppendEvent(role="system", content="hi"))
            client_t.join(timeout=2.0)
        finally:
            gw._heartbeat_stop.set()
            if gw._heartbeat_thread:
                gw._heartbeat_thread.join(timeout=1.0)
        assert state["err"] is None, state["err"]
        assert state["pongs"] == 3, f"expected 3 pongs, got {state['pongs']}"
        # Server saw at least 3 pongs → not dead.
        assert not gw._socket_dead
        # Reader updated _last_pong_at recently.
        assert time.monotonic() - gw._last_pong_at < 1.0
        # Seq numbers monotonic and at least one seen.
        assert state["seqs"], "client saw no seq numbers"
        for prev, curr in zip(state["seqs"], state["seqs"][1:]):
            assert curr > prev, f"seq not monotonic: {prev} -> {curr}"
    finally:
        transport.close()
