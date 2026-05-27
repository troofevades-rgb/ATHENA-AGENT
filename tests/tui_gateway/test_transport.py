"""Transport-layer tests for the TUI gateway.

These tests bypass Node entirely. A fake client socket connects to
the gateway's listener directly and exchanges real JSON-RPC frames.
This verifies that:

  - UDS and TCP transports both bind, accept, send, and receive
  - The UDS file is created with owner-only mode and unlinked on close
  - ATHENA_TUI_TRANSPORT override resolves correctly
  - Stale UDS paths from a prior crashed process are cleaned up

Added in TUI sprint step 3 alongside the UDS transport itself.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time

import pytest

from athena.tui_gateway.events import MessageAppendEvent
from athena.tui_gateway.server import (
    _TcpLoopbackTransport,
    _Transport,
    _UnixDomainTransport,
    _make_transport,
)


# ---- _make_transport resolution -----------------------------------------


def test_default_transport_is_uds_on_posix(monkeypatch):
    if sys.platform == "win32":
        pytest.skip("POSIX-only: Windows default is TCP")
    monkeypatch.delenv("ATHENA_TUI_TRANSPORT", raising=False)
    t = _make_transport()
    assert isinstance(t, _UnixDomainTransport)


def test_default_transport_is_tcp_on_windows(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows-only path")
    monkeypatch.delenv("ATHENA_TUI_TRANSPORT", raising=False)
    t = _make_transport()
    assert isinstance(t, _TcpLoopbackTransport)


def test_tcp_override_works_on_any_platform():
    t = _make_transport(override="tcp")
    assert isinstance(t, _TcpLoopbackTransport)


def test_uds_override_raises_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="UDS"):
        _make_transport(override="uds")


def test_unknown_override_raises():
    with pytest.raises(ValueError, match="unknown"):
        _make_transport(override="quic")


def test_env_var_override_picks_tcp(monkeypatch):
    monkeypatch.setenv("ATHENA_TUI_TRANSPORT", "tcp")
    t = _make_transport()
    assert isinstance(t, _TcpLoopbackTransport)


# ---- UDS file lifecycle -------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_uds_creates_owner_only_path_and_unlinks_on_close():
    t = _UnixDomainTransport()
    path = t._path
    assert not os.path.exists(path)
    t.bind()
    try:
        assert os.path.exists(path)
        mode = os.stat(path).st_mode & 0o777
        # owner bits set; group + other bits clear
        assert mode & 0o077 == 0, f"non-owner bits set: {oct(mode)}"
        assert mode & 0o700 != 0, f"no owner bits set: {oct(mode)}"
    finally:
        t.close()
    assert not os.path.exists(path), "UDS path should be unlinked after close"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_uds_replaces_stale_path():
    """A leftover socket file from a prior crashed gateway must
    not block a new gateway from binding at the same path."""
    t = _UnixDomainTransport()
    # Plant a stale file (regular file, not even a socket) at the
    # path we'are about to bind to.
    with open(t._path, "w") as f:
        f.write("stale")
    assert os.path.exists(t._path)
    t.bind()
    try:
        # The stale regular file was replaced by a real socket.
        st = os.stat(t._path)
        import stat as st_mod
        assert st_mod.S_ISSOCK(st.st_mode), (
            f"path is not a socket after bind: mode={oct(st.st_mode)}"
        )
    finally:
        t.close()


# ---- end-to-end round-trip on each transport ----------------------------


def _round_trip(transport: _Transport) -> None:
    """Bind the transport, connect a fake client, send a frame from
    server → client and a frame from client → server, verify both
    arrive intact. No Node, no Ink."""
    transport.bind()
    name, value = transport.env_var()

    # Connect from a worker thread because accept() and connect()
    # would deadlock if called on the same thread.
    accepted: list[socket.socket] = []
    accept_err: list[BaseException] = []

    def accept_worker():
        try:
            accepted.append(transport.accept(timeout_s=2.0))
        except BaseException as e:
            accept_err.append(e)

    t = threading.Thread(target=accept_worker, daemon=True)
    t.start()

    # Build the matching client socket.
    if name == "ATHENA_TUI_SOCK":
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(value)
    elif name == "ATHENA_TUI_PORT":
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", int(value)))
    else:
        raise AssertionError(f"unexpected env var: {name}")

    t.join(timeout=2.0)
    assert not accept_err, f"accept failed: {accept_err[0]!r}"
    assert accepted, "no inbound connection accepted"
    server_conn = accepted[0]

    # Server → client.
    server_frame = (
        json.dumps({
            "jsonrpc": "2.0",
            "method": "message.append",
            "params": {"role": "system", "content": "hello"},
        })
        + "\n"
    )
    server_conn.sendall(server_frame.encode("utf-8"))
    data = client.recv(4096).decode("utf-8")
    assert "message.append" in data, f"unexpected client recv: {data!r}"

    # Client → server.
    client_frame = (
        json.dumps({
            "jsonrpc": "2.0",
            "method": "user.input",
            "params": {"text": "ping"},
        })
        + "\n"
    )
    client.sendall(client_frame.encode("utf-8"))
    data = server_conn.recv(4096).decode("utf-8")
    assert "user.input" in data, f"unexpected server recv: {data!r}"
    assert "ping" in data

    client.close()
    server_conn.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_uds_round_trip_no_node():
    t = _UnixDomainTransport()
    try:
        _round_trip(t)
    finally:
        t.close()


def test_tcp_round_trip_no_node():
    t = _TcpLoopbackTransport()
    try:
        _round_trip(t)
    finally:
        t.close()
