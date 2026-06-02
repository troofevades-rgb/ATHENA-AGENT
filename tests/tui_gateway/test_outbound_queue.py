"""Outbound queue + stream.delta coalescing tests (TUI sprint step 5).

Two layers:
  - Direct unit tests of :class:`_OutboundQueue`: coalescing
    merges contiguous same-stream deltas
    drop policy never
    targets non-stream events
    close() wakes a blocked get.
  - End-to-end gateway pressure tests through a real socket
    with a fake-Python client:
        lossless single-stream burst,
    non-stream events survive heavy drop pressure.
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

from athena.tui_gateway import server as srv
from athena.tui_gateway.events import (
    MessageAppendEvent,
    StatusUpdateEvent,
    StreamDeltaEvent,
    StreamEndEvent,
    StreamStartEvent,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="end-to-end test uses UDS",
)


# ---- direct unit tests of _OutboundQueue --------------------------------


def test_coalesce_merges_contiguous_same_stream_deltas():
    q = srv._OutboundQueue(maxsize=100, coalesce_threshold=5)
    q.put(1, StreamStartEvent(stream_id="A"))
    for i in range(10):
        q.put(i + 2, StreamDeltaEvent(stream_id="A", text=f"x{i}"))
    # Coalesce threshold fired; 10 deltas should compress to 1.
    assert q.stats_coalesced > 0
    items = []
    while True:
        item = q.get(timeout=0.01)
        if item is None:
            break
        items.append(item)
    # Reassemble all delta text.
    text = "".join(
        getattr(ev, "text", "") for _seq, ev in items if getattr(ev, "type", None) == "stream.delta"
    )
    assert text == "x0x1x2x3x4x5x6x7x8x9"


def test_coalesce_does_not_cross_streams():
    """Deltas with different stream_ids are not merged even
    when adjacent."""
    q = srv._OutboundQueue(maxsize=100, coalesce_threshold=2)
    q.put(1, StreamDeltaEvent(stream_id="A", text="a"))
    q.put(2, StreamDeltaEvent(stream_id="B", text="b"))
    q.put(3, StreamDeltaEvent(stream_id="A", text="c"))
    # Even though coalesce ran, no merges happened.
    assert q.stats_coalesced == 0
    items = []
    while True:
        item = q.get(timeout=0.01)
        if item is None:
            break
        items.append(item)
    assert len(items) == 3


def test_drop_only_targets_stream_deltas():
    """Under maxsize pressure, non-stream events survive."""
    q = srv._OutboundQueue(maxsize=3, coalesce_threshold=100)
    q.put(1, StatusUpdateEvent(model="m1"))
    q.put(2, MessageAppendEvent(role="system", content="keep me"))
    q.put(3, StreamDeltaEvent(stream_id="A", text="old"))
    q.put(4, StreamDeltaEvent(stream_id="A", text="new"))
    # Pushed 4, max is 3 → oldest delta dropped, both non-stream
    # events still present.
    assert q.stats_dropped == 1
    items = []
    while True:
        item = q.get(timeout=0.01)
        if item is None:
            break
        items.append(item)
    types = [getattr(ev, "type", None) for _seq, ev in items]
    assert "status" in types
    assert "message.append" in types
    # The surviving stream.delta should be the newer one.
    deltas = [ev for _, ev in items if getattr(ev, "type", None) == "stream.delta"]
    assert len(deltas) == 1 and deltas[0].text == "new"


def test_close_unblocks_get():
    q = srv._OutboundQueue()
    result = []

    def waiter():
        result.append(q.get(timeout=2.0))

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.05)
    q.close()
    t.join(timeout=1.0)
    assert not t.is_alive(), "get did not return after close"
    assert result == [None]


# ---- end-to-end gateway pressure tests ----------------------------------


@pytest.fixture
def slow_heartbeats(monkeypatch):
    """Disable heartbeats for the stress tests so they don't
    interfere with delta accounting."""
    monkeypatch.setattr(srv, "_PING_INTERVAL_S", 100.0)
    monkeypatch.setattr(srv, "_DEAD_TIMEOUT_S", 100.0)


def _build_stub_gateway(transport, outbound=None):
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
    gw._outbound = outbound or srv._OutboundQueue()
    gw._writer_thread = None
    gw._writer_stop = threading.Event()
    # Writer-loop gating (Step 4b reconnect model): _writer_loop waits on
    # _conn_ready and touches _conn_died on socket errors. Without these
    # the writer AttributeErrors on its first tick and silently drops
    # every event — exactly the all-zero failures Linux CI surfaced.
    gw._conn_ready = threading.Event()
    gw._conn_died = threading.Event()
    return gw


def _fake_ink_drain(sock_path, sentinel, state, done_evt):
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.connect(sock_path)
        f = c.makefile("rwb", buffering=0)
        f.readline()  # server hello
        f.write(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "hello",
                        "params": {
                            "protocol_version": 2,
                            "client_version": "stress",
                            "capabilities": [],
                            "last_seq": 0,
                        },
                    }
                )
                + chr(10)
            ).encode("utf-8")
        )
        f.flush()
        while True:
            line = f.readline()
            if not line:
                break
            msg = json.loads(line.decode("utf-8"))
            method = msg.get("method")
            params = msg.get("params") or {}
            if method == "stream.delta":
                state.setdefault("deltas", []).append(params["text"])
            elif method == "message.append" and params.get("content") == sentinel:
                state.setdefault("other", []).append((method, params))
                break
            else:
                state.setdefault("other", []).append((method, params))
        c.close()
    except BaseException as e:
        state["err"] = e
    finally:
        done_evt.set()


def _drive_gateway(gw, transport):
    conn = transport.accept(timeout_s=2.0)
    gw._conn = conn
    gw._conn_reader = io.BufferedReader(socket.SocketIO(conn, "rb"))
    gw._do_handshake()
    gw._handshake_done = True
    # Mark the conn ready so the writer loop proceeds past its
    # _conn_ready gate (start() does this after a successful handshake).
    gw._conn_ready.set()
    gw._writer_thread = threading.Thread(target=gw._writer_loop, daemon=True)
    gw._writer_thread.start()
    return conn


def _teardown(gw, conn, transport):
    deadline = time.monotonic() + 2.0
    while len(gw._outbound) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    gw._writer_stop.set()
    gw._outbound.close()
    if gw._writer_thread:
        gw._writer_thread.join(timeout=1.0)
    try:
        conn.close()
    except OSError:
        pass
    transport.close()


def test_single_stream_burst_is_lossless(slow_heartbeats):
    """High-rate single-stream push → coalescing absorbs the burst,
    every byte of every delta is preserved end-to-end."""
    transport = srv._UnixDomainTransport()
    transport.bind()
    try:
        gw = _build_stub_gateway(
            transport,
            outbound=srv._OutboundQueue(maxsize=512, coalesce_threshold=32),
        )
        _, sock_path = transport.env_var()
        state = {}
        done = threading.Event()
        ct = threading.Thread(
            target=_fake_ink_drain,
            args=(sock_path, "DONE-LOSSLESS", state, done),
            daemon=True,
        )
        ct.start()
        conn = _drive_gateway(gw, transport)
        try:
            N = 5000
            expected = "".join(f"{i:04d}|" for i in range(N))
            gw.send_event(StreamStartEvent(stream_id="S"))
            for i in range(N):
                gw.send_event(StreamDeltaEvent(stream_id="S", text=f"{i:04d}|"))
            gw.send_event(StreamEndEvent(stream_id="S"))
            gw.send_event(MessageAppendEvent(role="system", content="DONE-LOSSLESS"))
            done.wait(timeout=10.0)
            assert state.get("err") is None, state.get("err")
            got = "".join(state.get("deltas", []))
            assert got == expected, f"lost text! got {len(got)} bytes vs expected {len(expected)}"
            final = gw.stats()
            assert final["outbound_coalesced"] > 0
            assert final["outbound_dropped"] == 0
        finally:
            _teardown(gw, conn, transport)
    finally:
        try:
            transport.close()
        except Exception:
            pass


def test_non_stream_events_never_dropped_under_pressure(slow_heartbeats):
    """When the queue saturates under interleaved-stream pressure
    (coalescing can't help), deltas get dropped but the status
    updates we interleave MUST survive."""
    transport = srv._UnixDomainTransport()
    transport.bind()
    try:
        # Tiny queue + low coalesce threshold to guarantee pressure.
        gw = _build_stub_gateway(
            transport,
            outbound=srv._OutboundQueue(maxsize=64, coalesce_threshold=32),
        )
        _, sock_path = transport.env_var()
        state = {}
        done = threading.Event()
        ct = threading.Thread(
            target=_fake_ink_drain,
            args=(sock_path, "DONE-PRESSURE", state, done),
            daemon=True,
        )
        ct.start()
        conn = _drive_gateway(gw, transport)
        try:
            STATUS_COUNT = 50
            for i in range(STATUS_COUNT):
                # Interleave 20 deltas across two streams to defeat
                # coalescing, then one status update.
                for j in range(20):
                    gw.send_event(
                        StreamDeltaEvent(
                            stream_id="A" if j % 2 == 0 else "B",
                            text=f"d{i}.{j}",
                        )
                    )
                gw.send_event(StatusUpdateEvent(tokens_up=i))
            gw.send_event(MessageAppendEvent(role="system", content="DONE-PRESSURE"))
            done.wait(timeout=10.0)
            assert state.get("err") is None, state.get("err")
            from collections import Counter

            methods = Counter(m for m, _ in state.get("other", []))
            # The whole point: every status survived.
            assert methods.get("status", 0) == STATUS_COUNT, (
                f"status events dropped! got {methods.get('status', 0)}/{STATUS_COUNT}"
            )
            # We expect some delta drops (pressure was real).
            final = gw.stats()
            assert final["outbound_dropped"] > 0, (
                "expected delta drops under pressure but got 0; maxsize may have been too generous"
            )
        finally:
            _teardown(gw, conn, transport)
    finally:
        try:
            transport.close()
        except Exception:
            pass
