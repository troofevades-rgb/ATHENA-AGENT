"""Step 4b reconnect-with-replay tests.

Two scenarios via fake-Python clients (no Node bundle needed):
  - queue-during-disconnect: events sent while no client is connected
    accumulate in the outbound queue and ship to the next client
  - ring-replay: client reconnects with last_seq < server's last
    shipped seq; ring buffer replays missed events before live ones
    resume

Both verify monotonic seq, zero duplicates, in-order delivery.
"""

from __future__ import annotations

import io
import json
import queue as _queue
import socket
import sys
import threading
import time

import pytest

from athena.tui_gateway.events import MessageAppendEvent
from athena.tui_gateway import server as srv


pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="end-to-end tests use UDS",
)


@pytest.fixture
def slow_heartbeats(monkeypatch):
    monkeypatch.setattr(srv, "_PING_INTERVAL_S", 100.0)
    monkeypatch.setattr(srv, "_DEAD_TIMEOUT_S", 100.0)


def _build_gateway(transport):
    gw = srv.TuiGateway.__new__(srv.TuiGateway)
    gw._transport = transport
    gw._proc = None
    gw._cmd_queue = _queue.Queue()
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
    gw._outbound = srv._OutboundQueue()
    gw._writer_thread = None
    gw._writer_stop = threading.Event()
    gw._ring = srv._EventRing()
    gw._accept_loop_thread = None
    gw._accept_stop = threading.Event()
    gw._conn_died = threading.Event()
    gw._conn_ready = threading.Event()
    gw._conn_lock = threading.Lock()
    return gw


def _start_threads(gw):
    gw._writer_thread = threading.Thread(target=gw._writer_loop, daemon=True)
    gw._writer_thread.start()
    gw._heartbeat_thread = threading.Thread(target=gw._heartbeat_loop, daemon=True)
    gw._heartbeat_thread.start()
    gw._conn_ready.set()
    gw._accept_loop_thread = threading.Thread(target=gw._accept_loop, daemon=True)
    gw._accept_loop_thread.start()
    gw._reader_thread = threading.Thread(target=gw._read_loop, daemon=True)
    gw._reader_thread.start()


def _client_hello_and_drain(sock_path, *, last_seq, n_to_recv=None,
                            timeout=1.5):
    received = []
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.connect(sock_path)
    f = c.makefile("rwb", buffering=0)
    f.readline()
    f.write((json.dumps({
        "jsonrpc": "2.0", "method": "hello",
        "params": {
            "protocol_version": 2, "client_version": "test",
            "capabilities": [], "last_seq": last_seq,
        },
    }) + chr(10)).encode())
    f.flush()
    if n_to_recv is not None:
        for _ in range(n_to_recv):
            received.append(json.loads(f.readline()))
    else:
        c.settimeout(timeout)
        try:
            while True:
                line = f.readline()
                if not line: break
                received.append(json.loads(line))
        except (socket.timeout, TimeoutError):
            pass
    c.close()
    return received


def test_queue_during_disconnect_ships_to_next_client(slow_heartbeats):
    """Events sent while no client is connected accumulate in the
    queue and ship to the next client after its handshake."""
    transport = srv._UnixDomainTransport()
    transport.bind()
    try:
        gw = _build_gateway(transport)
        _, sock_path = transport.env_var()
        # Client A: get 5 events, then drop
        a_recv = []
        def client_a():
            a_recv.extend(_client_hello_and_drain(
                sock_path, last_seq=0, n_to_recv=5))
        ta = threading.Thread(target=client_a, daemon=True); ta.start()
        conn_a = transport.accept(2.0)
        gw._conn = conn_a
        gw._conn_reader = io.BufferedReader(socket.SocketIO(conn_a, "rb"))
        gw._do_handshake()
        gw._last_pong_at = time.monotonic()
        gw._handshake_done = True
        _start_threads(gw)
        for i in range(5):
            gw.send_event(MessageAppendEvent(role="system", content=f"msg-{i}"))
        ta.join(timeout=3.0)
        last_seq_a = max(m["seq"] for m in a_recv)
        # Send 3 more while disconnected
        time.sleep(0.7)
        for i in range(3):
            gw.send_event(MessageAppendEvent(role="system", content=f"missed-{i}"))
        # Client B: connect, expect just the 3 queued
        b_recv = _client_hello_and_drain(sock_path, last_seq=last_seq_a)
        contents = [(m["params"] or {}).get("content") for m in b_recv]
        assert contents == ["missed-0", "missed-1", "missed-2"]
        seqs = [m["seq"] for m in b_recv]
        assert all(s > last_seq_a for s in seqs), f"duplicate seqs: {seqs}"
    finally:
        gw.close()
        try: transport.close()
        except Exception: pass


def test_ring_replay_serves_missed_events(slow_heartbeats):
    """Client B reconnects with last_seq < server's last shipped.
    Ring replays events between last_seq and server-state before
    the writer flushes queued events."""
    transport = srv._UnixDomainTransport()
    transport.bind()
    try:
        gw = _build_gateway(transport)
        _, sock_path = transport.env_var()
        a_recv = []
        def client_a():
            a_recv.extend(_client_hello_and_drain(
                sock_path, last_seq=0, n_to_recv=5))
        ta = threading.Thread(target=client_a, daemon=True); ta.start()
        conn_a = transport.accept(2.0)
        gw._conn = conn_a
        gw._conn_reader = io.BufferedReader(socket.SocketIO(conn_a, "rb"))
        gw._do_handshake()
        gw._last_pong_at = time.monotonic()
        gw._handshake_done = True
        _start_threads(gw)
        for i in range(5):
            gw.send_event(MessageAppendEvent(role="system", content=f"msg-{i}"))
        ta.join(timeout=3.0)
        time.sleep(0.7)
        for i in range(2):
            gw.send_event(MessageAppendEvent(role="system", content=f"queued-{i}"))
        # Client B with last_seq=3 (missed events 4,5,6,7)
        b_recv = _client_hello_and_drain(sock_path, last_seq=3)
        seqs = [m["seq"] for m in b_recv]
        contents = [(m["params"] or {}).get("content") for m in b_recv]
        assert seqs == [4, 5, 6, 7]
        assert contents == ["msg-3", "msg-4", "queued-0", "queued-1"]
    finally:
        gw.close()
        try: transport.close()
        except Exception: pass
