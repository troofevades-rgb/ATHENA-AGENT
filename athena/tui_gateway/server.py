"""TuiGateway — owns the Ink subprocess and the JSON-RPC channel.

Transport (TUI sprint step 3): selected by ``_make_transport()``:
  - **Unix domain socket** at ``/tmp/athena-tui-<pid>-<rand>.sock``
    on POSIX (default). Path is signaled via ``ATHENA_TUI_SOCK``.
  - **TCP loopback** on 127.0.0.1:<ephemeral> on Windows by default,
    and on any platform when ``ATHENA_TUI_TRANSPORT=tcp`` is set.
    Port is signaled via ``ATHENA_TUI_PORT``.
Stdio of the spawned process is left free for normal TTY use; the
protocol rides on a dedicated socket so it never collides with the
terminal.

Threading model:
  - Main thread reads commands via ``recv_command()`` (blocking).
  - A daemon reader thread drains the socket and feeds parsed
    commands into an internal Queue. Without this thread, a slow
    reader on the agent side could fill the OS socket buffer and
    block the TUI.
  - Writes go straight from the calling thread (the agent loop)
    through a Lock; JSON-RPC notifications are tiny so contention
    is negligible.

Subprocess lifecycle:
  - ``start()`` binds the listener, spawns ``node <bundle_path>``
    with the transport's env var set, then ``accept()``s a single
    inbound connection. The bundle is located at
    ``ui-tui/dist/main.js`` in dev installs and at
    ``athena/_tui_bundle/main.js`` in pip-installed wheels.
  - ``close()`` sends an exit event, then waits up to 2s for the
    process to terminate, then SIGTERM, then SIGKILL. The UDS
    socket file is unlinked on close.
  - If the TUI socket closes unexpectedly, ``recv_command()``
    returns ``None`` so the agent loop can exit gracefully.
"""

from __future__ import annotations

import abc
import collections
import dataclasses
import io
import json
import logging
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .events import (
    AskQuestionReplyCommand,
    Command,
    ConfirmReplyCommand,
    Event,
    ExitEvent,
    HelloCommand,
    HelloEvent,
    InterruptCommand,
    PingEvent,
    PongCommand,
    ProtocolErrorEvent,
    command_from_json_rpc,
)

logger = logging.getLogger(__name__)

# JSON-RPC error codes we emit. Sticking to the standard ones —
# the TUI doesn't need a richer vocabulary today.
_ERR_METHOD_NOT_FOUND = -32601
_ERR_PARSE = -32700


# Wire-protocol version (TUI sprint step 4). Bumped whenever an event
# or command is added/removed/changed in a way that an older peer
# can't process. Read from ``athena.tui_gateway.schema`` so the
# schema file remains the single source of truth.
def _protocol_version() -> int:
    from .schema import load_protocol

    return int(load_protocol().get("protocol_version", 1))


# Heartbeat cadence and dead-TUI threshold. The server pings every
# _PING_INTERVAL_S; if no pong arrives within _DEAD_TIMEOUT_S of the
# last successful pong, the TUI is declared dead.
_PING_INTERVAL_S = 5.0
_DEAD_TIMEOUT_S = 15.0


# ATHENA package version (best-effort; falls back to "unknown").
def _athena_version() -> str:
    try:
        from athena import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


# Capabilities the gateway advertises in its hello. Clients can use
# these to enable optional behaviors. Keep this list in lockstep
# with what the implementation actually supports.
_GATEWAY_CAPABILITIES: tuple[str, ...] = (
    "heartbeats",
    "seq",
    "coalesce",
)

# Outbound queue sizing. send_event enqueues; a writer thread
# drains. When len(queue) >= _OUTBOUND_COALESCE_THRESHOLD the
# enqueue path tries to merge contiguous stream.delta runs with
# the same stream_id (cheap O(n)). When len(queue) > _OUTBOUND_MAXSIZE
# the oldest stream.delta is dropped to bound memory.
_OUTBOUND_MAXSIZE = 1024
_OUTBOUND_COALESCE_THRESHOLD = int(_OUTBOUND_MAXSIZE * 0.8)

# Step 4b ring buffer: the last N (seq, event) pairs the writer
# thread successfully shipped to the socket. When a client
# reconnects with hello.last_seq=K, the server replays every
# entry where seq > K before resuming live traffic. Sized
# generously vs the queue so a multi-minute disconnect can be
# recovered without loss.
_RING_MAXSIZE = 500


def _restore_terminal() -> None:
    """Emit the ANSI sequences that undo Ink's terminal setup.

    Ink installs (1) alt-screen mode, (2) raw input, (3) hidden
    cursor. When the TUI subprocess exits cleanly, Ink's own
    cleanup restores all three. When the subprocess is killed
    (Ctrl+C path where Python's ``proc.kill()`` fires before Ink's
    SIGTERM handler runs, or any forced-shutdown path), the
    terminal stays in alt-screen + raw mode -- PowerShell renders
    its prompt into the invisible alt-screen, and the user is
    forced to close the terminal window entirely.

    Best-effort: writes to stderr so it doesn't collide with any
    final stdout the operator might be piping. A write failure
    (closed stderr, unusual stdio routing) is silently swallowed
    -- the cleanup is observability, not correctness; we must
    never raise out of shutdown.

    The sequences emitted:
      * ``ESC[?1049l`` -- exit alt-screen, restore main screen
      * ``ESC[?25h``   -- show cursor
      * ``ESC[?7h``    -- re-enable line wrap (Ink may have
                          disabled it for pixel-perfect layout)
      * ``ESC[0m``     -- reset SGR (colours / attributes)

    These work on every modern terminal emulator including
    Windows Terminal, ConPTY (PowerShell), and the legacy Win10
    conhost with VT mode enabled. The order matters: leaving
    alt-screen FIRST means the cursor / SGR reset lands on the
    visible (main) screen rather than the discarded alt buffer.
    """
    try:
        # Single contiguous write so partial-write doesn't leave
        # the terminal in a half-restored state.
        sys.stderr.write("\x1b[?1049l\x1b[?25h\x1b[?7h\x1b[0m")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _locate_bundle() -> Path:
    """Find the Ink bundle. Dev: ui-tui/dist/main.js. Wheel:
    athena/_tui_bundle/main.js. Raises FileNotFoundError so the
    caller can surface a clear error to the user."""
    pkg_root = Path(__file__).resolve().parent.parent
    # Wheel-shipped location (preferred for end users).
    wheel_path = pkg_root / "_tui_bundle" / "main.js"
    if wheel_path.exists():
        return wheel_path
    # Dev-tree fallback.
    repo_root = pkg_root.parent
    dev_path = repo_root / "ui-tui" / "dist" / "main.js"
    if dev_path.exists():
        return dev_path
    raise FileNotFoundError(
        "Ink TUI bundle not found. Looked for:\n"
        f"  {wheel_path}\n"
        f"  {dev_path}\n"
        "Build it with: cd ui-tui && bun run build"
    )


class _Transport(abc.ABC):
    """Listener-side transport for the gateway socket.

    The reads and writes themselves are transport-agnostic — both
    AF_INET and AF_UNIX expose the same ``socket.socket`` API once
    a connection is established. Only the bind/accept/cleanup parts
    differ, which this ABC abstracts.
    """

    @abc.abstractmethod
    def bind(self) -> None:
        """Bind the listener and start listening for one connection."""

    @abc.abstractmethod
    def env_var(self) -> tuple[str, str]:
        """``(name, value)`` to set in the subprocess's environment
        so the TUI client knows where to connect."""

    @abc.abstractmethod
    def accept(self, timeout_s: float) -> socket.socket:
        """Block up to ``timeout_s`` waiting for the subprocess to
        connect. Raises ``socket.timeout`` on expiry."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release the listener and any on-disk resources."""

    @abc.abstractmethod
    def describe(self) -> str:
        """Short human-readable identifier, used in logs."""


class _TcpLoopbackTransport(_Transport):
    """127.0.0.1:<ephemeral>. Default on Windows; fallback elsewhere."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._port: int | None = None

    def bind(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        self._sock = s
        self._port = s.getsockname()[1]

    def env_var(self) -> tuple[str, str]:
        if self._port is None:
            raise RuntimeError("TCP transport not bound")
        return ("ATHENA_TUI_PORT", str(self._port))

    def accept(self, timeout_s: float) -> socket.socket:
        # Capture locally — close() can null _sock from another
        # thread between our check and our .accept() call. Without
        # the capture, the accept-loop thread crashes with
        # AttributeError: 'NoneType' object has no attribute 'accept'
        # during gateway teardown.
        sock = self._sock
        if sock is None:
            raise RuntimeError("TCP transport not bound")
        sock.settimeout(timeout_s)
        conn, _ = sock.accept()
        return conn

    def close(self) -> None:
        sock = self._sock
        self._sock = None  # null first so concurrent accept() raises cleanly
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def describe(self) -> str:
        return f"tcp loopback :{self._port}" if self._port else "tcp loopback (unbound)"


class _UnixDomainTransport(_Transport):
    """AF_UNIX with an ephemeral ``/tmp/athena-tui-<pid>-<rand>.sock``.

    Default on POSIX. The path is created with mode 0600 (umask
    trick at bind time) and unlinked on close. PID+random suffix
    makes collisions with concurrent athena sessions vanishingly
    unlikely but we still defensively unlink stale paths.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._path = f"/tmp/athena-tui-{os.getpid()}-{secrets.token_hex(4)}.sock"

    def bind(self) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Restrict file mode to 0600 via umask at bind() — avoids
        # the race window of bind-then-chmod.
        old_umask = os.umask(0o077)
        try:
            try:
                os.unlink(self._path)
            except FileNotFoundError:
                pass
            s.bind(self._path)
        finally:
            os.umask(old_umask)
        s.listen(1)
        self._sock = s

    def env_var(self) -> tuple[str, str]:
        return ("ATHENA_TUI_SOCK", self._path)

    def accept(self, timeout_s: float) -> socket.socket:
        # Same capture-locally pattern as the TCP transport — avoids
        # AttributeError when close() runs concurrently with the
        # accept-loop thread.
        sock = self._sock
        if sock is None:
            raise RuntimeError("UDS transport not bound")
        sock.settimeout(timeout_s)
        conn, _ = sock.accept()
        return conn

    def close(self) -> None:
        sock = self._sock
        self._sock = None  # null first so concurrent accept() raises cleanly
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug(
                "failed to unlink UDS path %s",
                self._path,
                exc_info=True,
            )

    def describe(self) -> str:
        return f"unix-domain {self._path}"


def _make_transport(override: str | None = None) -> _Transport:
    """Pick a transport.

    Resolution order:
      1. ``override`` arg (mainly for tests)
      2. ``ATHENA_TUI_TRANSPORT`` env var (``tcp`` or ``uds``)
      3. Platform default: TCP on Windows, UDS on POSIX

    UDS-on-Windows raises — we deliberately do not support named
    pipes here (no callers need it yet; adding it later is its
    own step).
    """
    chosen = (override or os.environ.get("ATHENA_TUI_TRANSPORT", "")).lower()
    if chosen == "tcp":
        return _TcpLoopbackTransport()
    if chosen == "uds":
        if sys.platform == "win32":
            raise RuntimeError("UDS transport not supported on Windows")
        return _UnixDomainTransport()
    if chosen:
        raise ValueError(f"unknown ATHENA_TUI_TRANSPORT={chosen!r} (expected 'tcp' or 'uds')")
    if sys.platform == "win32":
        return _TcpLoopbackTransport()
    return _UnixDomainTransport()


class _OutboundQueue:
    """Bounded queue of pending outbound events with stream.delta
    coalescing and drop-oldest-delta-under-pressure policy.

    Why not :class:`queue.Queue`: we need to iterate the queue to
    coalesce, which isn't thread-safe on Queue. A deque + Condition
    + explicit lock gives us the same producer/consumer semantics
    plus the introspection.

    Items are ``(seq, event)`` tuples — seq is assigned at
    ``send_event`` time so coalescing/dropping preserves the
    seq monotonic-but-may-skip contract.
    """

    def __init__(
        self,
        *,
        maxsize: int = _OUTBOUND_MAXSIZE,
        coalesce_threshold: int = _OUTBOUND_COALESCE_THRESHOLD,
    ) -> None:
        self._items: collections.deque[tuple[int, Any]] = collections.deque()
        self._cond = threading.Condition()
        self._maxsize = maxsize
        self._coalesce_threshold = coalesce_threshold
        self._closed = False
        # Counters; read by gateway.stats().
        self.stats_queued = 0
        self.stats_coalesced = 0
        self.stats_dropped = 0

    def put(self, seq: int, event: Any) -> None:
        """Append. Coalesce + maybe drop. Wake the writer."""
        with self._cond:
            self._items.append((seq, event))
            self.stats_queued += 1
            if len(self._items) >= self._coalesce_threshold:
                self._coalesce_locked()
            if len(self._items) > self._maxsize:
                self._try_drop_oldest_delta_locked()
            self._cond.notify()

    def get(self, timeout: float | None = None) -> tuple[int, Any] | None:
        """Pop the oldest item. Returns None on timeout or close."""
        with self._cond:
            if not self._items:
                self._cond.wait(timeout=timeout)
            if self._closed and not self._items:
                return None
            if not self._items:
                return None
            return self._items.popleft()

    def close(self) -> None:
        """Mark closed and wake any waiter so the writer thread exits."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def __len__(self) -> int:
        with self._cond:
            return len(self._items)

    def _coalesce_locked(self) -> None:
        """Walk in-place; merge consecutive same-stream stream.delta
        into one item carrying the concatenated text + the newer seq.
        Lock must be held."""
        i = 1
        while i < len(self._items):
            prev_seq, prev_ev = self._items[i - 1]
            curr_seq, curr_ev = self._items[i]
            if (
                getattr(prev_ev, "type", None) == "stream.delta"
                and getattr(curr_ev, "type", None) == "stream.delta"
                and getattr(prev_ev, "stream_id", None) == getattr(curr_ev, "stream_id", None)
            ):
                merged = dataclasses.replace(
                    prev_ev,
                    text=prev_ev.text + curr_ev.text,
                )
                # Keep the newer seq — the client's lastSeq jumps to
                # the highest one in the run.
                self._items[i - 1] = (curr_seq, merged)
                del self._items[i]
                self.stats_coalesced += 1
                # Don't advance i — the new neighbor may also merge.
            else:
                i += 1

    def _try_drop_oldest_delta_locked(self) -> None:
        """If the queue is over capacity, drop the oldest
        stream.delta (or no-op if there isn't one). Other event
        types are protected."""
        for i, (_seq, ev) in enumerate(self._items):
            if getattr(ev, "type", None) == "stream.delta":
                del self._items[i]
                self.stats_dropped += 1
                return
        # Nothing droppable: queue grows past maxsize. Log so the
        # operator notices sustained pressure.
        logger.warning(
            "outbound queue past maxsize (%d) with no droppable "
            "stream.delta — non-stream backpressure",
            self._maxsize,
        )


class _EventRing:
    """Bounded buffer of the most-recent shipped events for
    reconnect-with-replay (step 4b).

    Only events the writer thread SUCCESSFULLY shipped to the
    socket land here. Queued-but-not-yet-shipped events live on
    `_OutboundQueue` and reach the next client via normal drain.
    The ring is therefore "what the wire saw" — exactly what
    a client should be replayed if it dropped its connection.

    Thread-safe via a single lock. Indexed by monotonic seq;
    `replay_since(N)` returns every entry with seq > N in order.
    """

    def __init__(self, *, maxsize: int = _RING_MAXSIZE) -> None:
        self._items: collections.deque[tuple[int, Any]] = collections.deque(maxlen=maxsize)
        self._lock = threading.Lock()

    def record(self, seq: int, event: Any) -> None:
        """Append. When the ring is at maxsize, the oldest entry
        is dropped automatically (deque maxlen semantics)."""
        with self._lock:
            self._items.append((seq, event))

    def replay_since(self, last_seq: int) -> list[tuple[int, Any]]:
        """Snapshot of (seq, event) pairs with seq > last_seq,
        ordered oldest-first. Returns a copy so the caller can
        iterate without holding the lock."""
        with self._lock:
            return [(s, e) for (s, e) in self._items if s > last_seq]

    def oldest_seq(self) -> int | None:
        """The seq of the oldest still-buffered event, or None
        when empty. A client requesting replay from a seq older
        than this has missed events the ring has already evicted —
        the agent should surface a 'replay incomplete' notice (TBD)."""
        with self._lock:
            if not self._items:
                return None
            return self._items[0][0]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class _HandshakeError(Exception):
    """Raised when the hello exchange fails. Caller is responsible
    for closing the gateway and surfacing a clean error."""


class TuiGateway:
    """Spawn the Ink TUI and pump events/commands through stdio."""

    def __init__(
        self,
        *,
        bundle_path: Path | None = None,
        node_bin: str | None = None,
        accept_timeout_s: float = 5.0,
        tty_passthrough: bool = True,
    ) -> None:
        """``tty_passthrough`` controls whether the subprocess
        inherits the parent's stdin/stdout. True for normal
        interactive use (Ink needs the real TTY for keyboard +
        render). False for headless contexts where the parent
        doesn't have a real terminal (pytest, CI, daemons); in
        that case stdio is redirected to DEVNULL and Ink runs
        in non-interactive mode."""
        self._bundle = bundle_path or _locate_bundle()
        self._node = node_bin or os.environ.get("ATHENA_NODE_BIN", "node")
        self._proc: subprocess.Popen[bytes] | None = None
        self._cmd_queue: queue.Queue[Command | None] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._closed = False
        # Transport selected by _make_transport(). Defaults to
        # UDS on POSIX, TCP on Windows; ``ATHENA_TUI_TRANSPORT``
        # env var overrides. Stdio of the spawned process stays
        # free for keyboard input + UI render; the protocol
        # rides on this dedicated channel.
        self._transport: _Transport = _make_transport()
        self._conn: socket.socket | None = None
        self._conn_reader: io.BufferedReader | None = None
        self._accept_timeout_s = accept_timeout_s
        self._tty_passthrough = tty_passthrough
        # Flips to True when the socket dies mid-session (TUI
        # crashed, network hiccup, etc). Once dead, send_event
        # raises so callers know not to keep trying.
        self._socket_dead = False
        # Monotonic sequence number injected into every outbound
        # event's JSON-RPC envelope under the top-level "seq" key.
        # Wraps the existing JSON-RPC notification — see ADR in
        # TUI_SPRINT.md decision log.
        self._next_seq = 0
        self._seq_lock = threading.Lock()
        # Heartbeat plumbing. _last_pong_at is set on every pong
        # the reader thread sees; the heartbeat thread checks it
        # against time.monotonic() to detect a dead TUI.
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._last_pong_at: float = 0.0
        self._handshake_done = False
        # Step 5: bounded outbound queue + writer thread. send_event
        # enqueues; the writer drains and writes to the socket. Pre-
        # handshake writes still go through _send_event_raw which
        # bypasses the queue (the writer thread hasn't started yet).
        self._outbound = _OutboundQueue()
        self._writer_thread: threading.Thread | None = None
        self._writer_stop = threading.Event()
        # Step 4b ring buffer: the writer thread records every
        # successfully-shipped (seq, event) pair here. Used by
        # the reconnect-with-replay path on the next client's hello.
        self._ring = _EventRing()
        # Step 4b accept-loop: persistent thread that handles
        # reconnects after the first client dies. start() still
        # accepts the first conn synchronously; this thread takes
        # over for all subsequent (re)accepts.
        self._accept_loop_thread: threading.Thread | None = None
        self._accept_stop = threading.Event()
        # Set by the per-conn reader thread when it sees EOF; the
        # accept loop watches this to know when to re-accept.
        self._conn_died = threading.Event()
        # Set by the accept loop after a new conn is fully bound
        # and handshake+replay are complete; the writer + heartbeat
        # threads wait on this when self._conn is None.
        self._conn_ready = threading.Event()
        # Guards self._conn / self._conn_reader swaps during reconnect.
        self._conn_lock = threading.Lock()

    # ---- lifecycle ----------------------------------------------

    def start(self) -> None:
        """Bind the listener, spawn the Ink subprocess, accept
        its inbound connection. Raises FileNotFoundError if
        ``node`` is missing or the bundle isn't on disk."""
        if self._proc is not None:
            raise RuntimeError("gateway already started")

        # Bind the transport BEFORE spawning so the subprocess
        # can connect immediately on startup.
        self._transport.bind()
        env_name, env_value = self._transport.env_var()
        logger.debug("tui gateway transport: %s", self._transport.describe())

        env = os.environ.copy()
        env[env_name] = env_value
        if self._tty_passthrough:
            # Production: inherit real terminal stdio. Ink reads
            # the keyboard from stdin and renders to stdout.
            popen_stdin: Any = sys.stdin
            popen_stdout: Any = sys.stdout
            popen_stderr: Any = sys.stderr
        else:
            # Headless: parent has no real TTY (pytest, daemon).
            # DEVNULL stdin so Ink's input handlers see immediate
            # EOF; capture stdout/stderr so test output is clean.
            popen_stdin = subprocess.DEVNULL
            popen_stdout = subprocess.DEVNULL
            popen_stderr = subprocess.DEVNULL
        self._proc = subprocess.Popen(  # noqa: S603
            [self._node, str(self._bundle)],
            stdin=popen_stdin,
            stdout=popen_stdout,
            stderr=popen_stderr,
            env=env,
        )

        try:
            conn = self._transport.accept(self._accept_timeout_s)
        except TimeoutError as e:
            self.close()
            raise RuntimeError(
                f"TUI did not connect to gateway within "
                f"{self._accept_timeout_s}s — bundle probably failed to start"
            ) from e
        self._conn = conn
        # Buffered reader for line-oriented reads.
        self._conn_reader = io.BufferedReader(socket.SocketIO(conn, "rb"))  # type: ignore[arg-type]

        # Synchronous hello handshake BEFORE starting the reader
        # thread. If versions don't match we close cleanly with
        # ProtocolErrorEvent rather than letting the reader loop
        # discover the problem asynchronously.
        try:
            self._do_handshake()
        except _HandshakeError as e:
            logger.warning("hello handshake failed: %s", e)
            self.close()
            raise RuntimeError(f"TUI handshake failed: {e}") from e

        # Mark last_pong baseline so heartbeats start counting from
        # successful handshake.
        self._last_pong_at = time.monotonic()
        self._handshake_done = True

        self._reader_thread = threading.Thread(
            target=self._read_loop, name="athena-tui-reader", daemon=True
        )
        self._reader_thread.start()

        # Writer thread: drains the outbound queue, writes to the
        # socket. send_event enqueues. The thread must be alive
        # before the heartbeat thread (which calls send_event)
        # starts.
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="athena-tui-writer",
            daemon=True,
        )
        self._writer_thread.start()

        # Heartbeat thread: pings every _PING_INTERVAL_S, declares
        # dead if no pong within _DEAD_TIMEOUT_S of the last seen.
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="athena-tui-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

        # First connection is live; let writer + heartbeat proceed.
        self._conn_ready.set()

        # Step 4b: accept-loop handles all subsequent reconnects.
        # When the current reader thread sees EOF, it signals
        # _conn_died; this loop closes the dead conn, accepts a
        # new one, handshakes (replaying ring per client's last_seq),
        # spawns a new reader. Persists for the life of the gateway.
        self._accept_loop_thread = threading.Thread(
            target=self._accept_loop,
            name="athena-tui-accept-loop",
            daemon=True,
        )
        self._accept_loop_thread.start()

    def close(self, *, timeout_s: float = 2.0) -> None:
        """Tell the TUI to exit and reap the process."""
        if self._closed:
            return
        self._closed = True
        try:
            self.send_event(ExitEvent(reason="gateway shutdown"))
        except Exception:  # noqa: BLE001 — already shutting down
            pass
        # Close the protocol socket so the TUI's stdin EOF handler
        # also fires (belt + suspenders).
        #
        # Capture ``self._conn`` into a local — the reader/writer
        # thread can null it out between our check and our use when
        # the socket dies during shutdown (observed:
        # AttributeError: 'NoneType' object has no attribute 'close'
        # at this site under burst-write tests). Holding the
        # reference locally makes the close idempotent against that
        # race.
        conn = self._conn
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        try:
            self._transport.close()
        except Exception:  # noqa: BLE001 — already shutting down
            logger.debug("transport close failed", exc_info=True)
        # Step 4b: stop the accept-loop first so it doesn't try
        # to re-bind a new conn while we're tearing down.
        self._accept_stop.set()
        self._conn_died.set()  # unblock its main wait
        if self._accept_loop_thread is not None and self._accept_loop_thread.is_alive():
            self._accept_loop_thread.join(timeout=2.0)
        # Stop the heartbeat thread before reaping the reader.
        # The stop event also unblocks the wait() inside the loop.
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.0)
        # Step 4b: tell any recv_command caller in the REPL that
        # the gateway is going down (replaces the per-disconnect
        # EOF signal the reader used to emit).
        self._cmd_queue.put(None)
        # Stop the writer thread. The queue.close() wakes it from
        # a blocking get; the stop event tells it to exit even if
        # there are still items to drain. _conn_ready.set() also
        # unblocks if it was waiting on the conn-ready gate.
        self._writer_stop.set()
        self._conn_ready.set()
        self._outbound.close()
        if self._writer_thread is not None and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1.0)
        # Reap the reader thread so it can't put stale frames
        # into the queue (or read from a recycled fd) after we
        # think the gateway is gone. Daemon thread guarantees we
        # don't deadlock the parent if the reader is genuinely
        # stuck — short bounded join then move on.
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        proc = self._proc
        if proc is None:
            _restore_terminal()
            return
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            logger.warning("TUI did not exit in %ss; terminating", timeout_s)
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                logger.warning("TUI did not respond to SIGTERM; killing")
                proc.kill()
        # Restore the terminal state regardless of whether the TUI
        # exited cleanly or was force-killed. Ink installs alt-screen
        # + raw mode when it boots; if it doesn't get to run its
        # own cleanup (Ctrl+C path where Ink's exit() unmounts React
        # but Node is forcibly terminated before its SIGTERM/EOF
        # cleanup runs), the user is left with a "frozen" terminal --
        # PowerShell's prompt renders into an alt-screen the user
        # can't see, requiring them to close the window entirely.
        # Surfaced repeatedly on Windows ConPTY.
        _restore_terminal()

    # ---- handshake + heartbeat ---------------------------------

    def _do_handshake(self) -> None:
        """Send our hello, read the client's hello, validate.

        Runs synchronously on the main thread so any error short-
        circuits start() before the reader thread is even spawned.
        Raises ``_HandshakeError`` for any failure — caller logs
        and closes.
        """
        # 1. Send our hello first so the client knows what it's
        # talking to before deciding whether to proceed.
        my_hello = HelloEvent(
            protocol_version=_protocol_version(),
            athena_version=_athena_version(),
            capabilities=list(_GATEWAY_CAPABILITIES),
            current_seq=0,
        )
        try:
            self._send_event_raw(my_hello)
        except OSError as e:
            raise _HandshakeError(f"failed to send hello: {e}") from e

        # 2. Block on the client's hello reply, bounded by the
        # accept timeout (same as we waited for them to connect).
        if self._conn is None or self._conn_reader is None:
            raise _HandshakeError("no connection or reader")
        self._conn.settimeout(self._accept_timeout_s)
        try:
            raw = self._conn_reader.readline()
        except TimeoutError as e:
            raise _HandshakeError(
                f"client did not send hello within {self._accept_timeout_s}s"
            ) from e
        finally:
            # Restore blocking behavior for the reader thread.
            try:
                self._conn.settimeout(None)
            except OSError:
                pass

        if not raw:
            raise _HandshakeError("client closed connection without hello")
        try:
            frame = json.loads(raw.decode("utf-8", errors="replace").strip())
        except json.JSONDecodeError as e:
            self._send_protocol_error("malformed_hello", f"could not parse hello: {e}")
            raise _HandshakeError(f"malformed client hello: {e}") from e

        if not isinstance(frame, dict) or frame.get("method") != "hello":
            self._send_protocol_error(
                "malformed_hello",
                f"expected hello as first frame, got method={frame!r}",
            )
            raise _HandshakeError(f"expected first frame to be hello, got {frame!r}")
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        client_hello = HelloCommand(
            protocol_version=int(params.get("protocol_version", 0)),
            client_version=str(params.get("client_version", "")),
            capabilities=list(params.get("capabilities", []) or []),
            last_seq=int(params.get("last_seq", 0)),
        )

        # 3. Validate. Only protocol_version is hard-required to
        # match; capabilities are advisory.
        my_pv = _protocol_version()
        if client_hello.protocol_version != my_pv:
            self._send_protocol_error(
                "protocol_version_mismatch",
                (
                    f"gateway speaks protocol v{my_pv}, "
                    f"client speaks v{client_hello.protocol_version} — "
                    "rebuild the bundle"
                ),
            )
            raise _HandshakeError(
                f"protocol version mismatch: server={my_pv} client={client_hello.protocol_version}"
            )

        logger.debug(
            "tui handshake ok: client_version=%r capabilities=%r last_seq=%d",
            client_hello.client_version,
            client_hello.capabilities,
            client_hello.last_seq,
        )

        # Step 4b: replay missed events if client requested.
        if client_hello.last_seq > 0:
            count = self._replay_to_current_conn(client_hello.last_seq)
            logger.info(
                "tui replay: shipped %d event(s) since seq %d",
                count,
                client_hello.last_seq,
            )

    def _send_protocol_error(self, code: str, message: str) -> None:
        """Best-effort: send a ProtocolErrorEvent so the client can
        render a clear message before we close. Failures are
        swallowed — we're already in an error path."""
        try:
            self._send_event_raw(ProtocolErrorEvent(code=code, message=message))
        except Exception:  # noqa: BLE001
            logger.debug("could not emit protocol.error", exc_info=True)

    def _accept_loop(self) -> None:
        """Persistent reconnect handler. Runs for the life of the
        gateway. On conn death: closes the dead conn, accepts a
        new one, runs handshake + replay, spawns a fresh reader.

        The first connection is bound by start() synchronously;
        this loop only handles the second-and-beyond accepts.
        """
        # Long timeout per accept() so the loop is responsive to
        # close() without burning CPU.
        accept_timeout_s = 1.0
        while not self._accept_stop.is_set():
            # Wait for the current connection to die (or for the
            # gateway to shut down).
            if not self._conn_died.wait(timeout=0.5):
                continue
            self._conn_died.clear()
            if self._accept_stop.is_set():
                return
            # Tear down the dead conn.
            with self._conn_lock:
                self._conn_ready.clear()
                old_conn = self._conn
                self._conn = None
                self._conn_reader = None
            if old_conn is not None:
                try:
                    old_conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    old_conn.close()
                except OSError:
                    pass
            logger.info("tui conn died; awaiting reconnect")

            # Accept a new conn. Loop with short timeout so
            # close() can preempt.
            new_conn: socket.socket | None = None
            while not self._accept_stop.is_set():
                try:
                    new_conn = self._transport.accept(accept_timeout_s)
                    break
                except TimeoutError:
                    continue
                except (OSError, RuntimeError) as e:
                    # Transport closed (close() was called) or other
                    # OS error — abort the loop. RuntimeError is the
                    # expected "transport not bound" raised by the
                    # transport's accept() when close() has nulled
                    # the socket; it's a normal shutdown condition,
                    # not a crash.
                    logger.debug("accept-loop aborting: %s", e)
                    return
            if new_conn is None:
                return  # shutdown

            # Bind the new conn under lock.
            with self._conn_lock:
                self._conn = new_conn
                self._conn_reader = io.BufferedReader(
                    socket.SocketIO(new_conn, "rb"),  # type: ignore[arg-type]
                )

            # Re-do handshake on the new conn (also handles replay).
            try:
                self._do_handshake()
            except _HandshakeError as e:
                logger.warning(
                    "reconnect handshake failed; closing: %s",
                    e,
                )
                with self._conn_lock:
                    if self._conn is not None:
                        try:
                            self._conn.close()
                        except OSError:
                            pass
                    self._conn = None
                    self._conn_reader = None
                # Fall back into the outer loop to wait for another
                # client. We don't reset _conn_died; outer iteration
                # will wait for the next death signal that never
                # comes... so we set it manually so a future client
                # can connect.
                self._conn_died.set()
                continue

            # Reset heartbeat baseline and signal writer/heartbeat
            # to resume.
            self._last_pong_at = time.monotonic()
            self._conn_ready.set()
            logger.info(
                "tui reconnected; ring depth=%d",
                len(self._ring),
            )

            # Spawn a fresh reader for this connection era.
            self._reader_thread = threading.Thread(
                target=self._read_loop,
                name="athena-tui-reader",
                daemon=True,
            )
            self._reader_thread.start()

    def _replay_to_current_conn(self, last_seq: int) -> int:
        """Replay all ring-buffered events with seq > last_seq
        directly to self._conn. Bypasses the outbound queue so
        the replayed events arrive before any live events the
        writer flushes after handshake completes.

        Returns the count of frames replayed.
        """
        if self._conn is None:
            return 0
        entries = self._ring.replay_since(last_seq)
        if not entries:
            return 0
        oldest_available = self._ring.oldest_seq()
        if oldest_available is not None and oldest_available > last_seq + 1:
            # Client missed events that are no longer in the ring.
            # Best we can do: replay what we have and let the gap
            # be visible to the model. (Future: emit a synthetic
            # "replay incomplete" status event.)
            logger.warning(
                "replay incomplete: client last_seq=%d, ring oldest=%d (missing %d events)",
                last_seq,
                oldest_available,
                oldest_available - (last_seq + 1),
            )
        for seq, event in entries:
            payload = {
                "jsonrpc": "2.0",
                "method": event.type,
                "params": _strip_type(asdict(event)),
                "seq": seq,
            }
            line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
            with self._write_lock:
                if self._conn is None:
                    return 0
                try:
                    self._conn.sendall(line)
                except (BrokenPipeError, OSError):
                    return 0
        return len(entries)

    def _heartbeat_loop(self) -> None:
        """Daemon thread: emit ping every _PING_INTERVAL_S, declare
        dead if no pong arrives within _DEAD_TIMEOUT_S of the last
        seen pong."""
        while not self._heartbeat_stop.is_set():
            # Sleep first so we don't fire a ping right after the
            # handshake's pong baseline (gives the client room to
            # respond to the first ping before we ever notice it
            # missed).
            if self._heartbeat_stop.wait(timeout=_PING_INTERVAL_S):
                return
            if self._closed:
                return
            # Step 4b: between connection eras, skip the ping —
            # there's no peer to receive it. The pong timer also
            # pauses (we reset _last_pong_at on every successful
            # handshake).
            if not self._conn_ready.is_set():
                continue
            # Send ping.
            try:
                self.send_event(PingEvent())
            except RuntimeError:
                # send_event guarded; queue or transient issue.
                continue
            # Check dead-TUI threshold.
            age = time.monotonic() - self._last_pong_at
            if age > _DEAD_TIMEOUT_S:
                logger.warning(
                    "TUI heartbeat lost: %.1fs since last pong (threshold %.1fs)",
                    age,
                    _DEAD_TIMEOUT_S,
                )
                self._send_protocol_error(
                    "tui_heartbeat_lost",
                    f"no pong for {age:.1f}s (threshold {_DEAD_TIMEOUT_S}s)",
                )
                self._socket_dead = True
                return

    def stats(self) -> dict[str, Any]:
        """Snapshot of gateway counters. Useful for tests and
        for surfacing backpressure in long-running sessions.

        Returns: ``{
            "next_seq": int,
            "outbound_queued": int,         # cumulative
            "outbound_coalesced": int,      # cumulative
            "outbound_dropped": int,        # cumulative
            "outbound_depth": int,          # current
            "ring_depth": int,              # events available for replay
            "ring_oldest_seq": int | None,  # earliest replayable seq
            "socket_dead": bool,
        }``.
        """
        return {
            "next_seq": self._next_seq,
            "outbound_queued": self._outbound.stats_queued,
            "outbound_coalesced": self._outbound.stats_coalesced,
            "outbound_dropped": self._outbound.stats_dropped,
            "outbound_depth": len(self._outbound),
            "ring_depth": len(self._ring),
            "ring_oldest_seq": self._ring.oldest_seq(),
            "socket_dead": self._socket_dead,
        }

    def _writer_loop(self) -> None:
        """Drain the outbound queue and write each item to the socket.

        Persistent across reconnects (step 4b): when self._conn
        is None (between connection eras), the writer blocks on
        _conn_ready until the accept-loop establishes a new
        conn. Items already in the queue are NOT dropped during
        the gap — they ship to the next client as soon as it
        connects.
        """
        while not self._writer_stop.is_set():
            # If there's no active conn, wait for one. Bounded
            # timeout so close() can preempt.
            if not self._conn_ready.is_set():
                if not self._conn_ready.wait(timeout=0.5):
                    continue
                if self._writer_stop.is_set():
                    return
            item = self._outbound.get(timeout=0.1)
            if item is None:
                if self._writer_stop.is_set():
                    return
                continue
            seq, event = item
            payload = {
                "jsonrpc": "2.0",
                "method": event.type,
                "params": _strip_type(asdict(event)),
                "seq": seq,
            }
            line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
            with self._write_lock:
                if self._conn is None:
                    # Conn was torn down between get() and write.
                    # Re-queue the item so it ships to the next
                    # client after replay. seq stays the same.
                    self._outbound.put(seq, event)
                    continue
                try:
                    self._conn.sendall(line)
                except (BrokenPipeError, OSError) as e:
                    # Step 4b: conn died mid-send. Don't set
                    # _socket_dead permanently — the accept-loop
                    # will re-bind a new conn. Just clear ready and
                    # re-queue the failed item.
                    logger.warning(
                        "TUI socket closed in writer thread; awaiting reconnect: %s",
                        e,
                    )
                    self._conn_ready.clear()
                    self._conn_died.set()
                    # Re-queue (preserves seq so ring stays
                    # consistent post-replay).
                    self._outbound.put(seq, event)
                    continue
            # Successfully shipped — record into the ring buffer
            # so a reconnecting client can replay it. PingEvent
            # is excluded: pings are stateless and replaying them
            # would just trigger a flood of pongs for events long
            # past, with no meaning to the user.
            if event.type != "ping":
                self._ring.record(seq, event)

    # ---- writes (gateway → TUI) ---------------------------------

    def send_event(self, event: Event) -> None:
        """Enqueue an event for the writer thread to ship.

        Allocates the seq number synchronously (preserves event-
        creation order even if the writer drains later). The actual
        socket write happens on the writer thread. Stream.delta
        events may be coalesced or dropped under queue pressure
        (see :class:`_OutboundQueue`).

        Step 4b: accepts events even when no client is currently
        connected — they queue and ship to the next client. Only
        raises when the gateway is permanently shutting down
        (after :meth:`close`).
        """
        if self._closed or self._writer_stop.is_set():
            raise RuntimeError("gateway is shut down")
        with self._seq_lock:
            self._next_seq += 1
            seq = self._next_seq
        self._outbound.put(seq, event)

    def _send_event_raw(self, event: Event) -> None:
        """Pre-handshake send. Skips the seq counter (handshake frames
        are conceptually pre-seq) and skips the dead-socket check
        so initial hello can be emitted while ``_handshake_done``
        is still False. Internal use only."""
        if self._conn is None:
            raise RuntimeError("no connection")
        payload = {
            "jsonrpc": "2.0",
            "method": event.type,
            "params": _strip_type(asdict(event)),
        }
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        # Recheck under lock — _conn can be nulled between the early
        # guard above and this point by the reconnect thread. Without
        # this, hello/protocol-error sends can crash with AttributeError
        # if the client disconnects mid-handshake.
        with self._write_lock:
            conn = self._conn
            if conn is None:
                raise RuntimeError("connection lost before write")
            conn.sendall(line)

    # ---- reads (TUI → gateway) ----------------------------------

    def recv_command(self, *, timeout: float | None = None) -> Command | None:
        """Block until the TUI sends a command. Returns ``None``
        when the TUI exits or the gateway is closed."""
        try:
            return self._cmd_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _read_loop(self) -> None:
        """Drain socket, parse JSON-RPC frames, dispatch commands.

        Most commands land on ``_cmd_queue`` for the main REPL to
        drain via ``recv_command()``. The exception is
        ``ConfirmReplyCommand``: it must be delivered to the
        waiting ``ui.confirm()`` call directly, because the REPL
        loop is blocked inside ``agent.run_turn()`` when a
        confirm is in flight — if we queued the reply and waited
        for the REPL to drain it, the agent would block until
        timeout (5 minutes) and auto-deny.
        """
        reader = self._conn_reader
        if reader is None:
            return
        try:
            while True:
                # Hand-rolled readline so we can distinguish a
                # clean EOF (returns b"") from a stream error
                # (raises OSError) — the for-loop form swallows
                # the difference.
                raw = reader.readline()
                if not raw:
                    break  # clean EOF
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                cmd = self._parse_frame(line)
                if cmd is None:
                    continue
                # Pong is internal heartbeat plumbing — the reader
                # records the timestamp and never surfaces it to
                # recv_command callers.
                if isinstance(cmd, PongCommand):
                    self._last_pong_at = time.monotonic()
                    continue
                if isinstance(cmd, ConfirmReplyCommand):
                    self._dispatch_confirm_reply(cmd)
                    continue
                if isinstance(cmd, AskQuestionReplyCommand):
                    self._dispatch_ask_question_reply(cmd)
                    continue
                if isinstance(cmd, InterruptCommand):
                    # Three-step interrupt:
                    #   1. ALWAYS enqueue the InterruptCommand so an
                    #      idle ``recv_command`` blocked in
                    #      queue.get() wakes up. Without this,
                    #      ``_thread.interrupt_main()`` alone is
                    #      unreliable on Windows: the KeyboardInterrupt
                    #      is queued for delivery at the next bytecode
                    #      boundary, but a main thread parked in the
                    #      C-level condition-var wait inside queue.get
                    #      never reaches that boundary. Users saw this
                    #      as "Ctrl+C does nothing at the prompt -- I
                    #      have to kill the terminal." Putting the
                    #      command on the queue first guarantees the
                    #      idle case unblocks immediately.
                    #   2. Raise KeyboardInterrupt on the main thread
                    #      via ``_thread.interrupt_main()`` so the
                    #      MID-TURN case (main is inside agent.run_turn
                    #      not recv_command) unwinds via except
                    #      KeyboardInterrupt. The REPL loop's
                    #      ``isinstance(cmd, InterruptCommand)``
                    #      handler in __main__.py decides what to do
                    #      with the queued cmd: at idle it exits, in
                    #      a turn it's a no-op (run_turn already
                    #      caught the KeyboardInterrupt).
                    #   3. Fire cancel hooks (close provider httpx
                    #      clients, etc.) so the main thread ACTUALLY
                    #      reaches a bytecode boundary. Without (3),
                    #      a blocked ``socket.recv`` inside an LLM
                    #      stream can sit in C code for many minutes
                    #      while the queued KeyboardInterrupt waits.
                    import _thread

                    self._cmd_queue.put(cmd)
                    try:
                        _thread.interrupt_main()
                    except RuntimeError:
                        # Some embedded contexts don't allow this.
                        # The queue.put above already handles the
                        # idle wake-up so we're not stuck either way.
                        pass
                    try:
                        from .. import interrupt_hooks

                        interrupt_hooks.fire_cancel_hooks()
                    except Exception:  # noqa: BLE001
                        logger.exception("cancel hooks dispatch failed")
                    continue
                self._cmd_queue.put(cmd)
        except OSError as e:
            # Socket closed mid-read or transient error.
            logger.info("TUI reader loop exited: %s", e)
        finally:
            # Step 4b: signal the accept-loop that this connection
            # is dead. The accept-loop will close the conn and
            # wait for a new one. We do NOT put None on _cmd_queue
            # here — that would force the REPL to exit on every
            # disconnect. Instead, _cmd_queue gets a None only
            # when close() is called (gateway shutting down for real).
            self._conn_died.set()

    def _dispatch_confirm_reply(self, cmd: ConfirmReplyCommand) -> None:
        """Hand a confirm reply straight to the waiting agent
        thread via the ui module's per-request queue. Bypasses
        ``_cmd_queue`` so it doesn't sit waiting for the REPL
        loop to call ``recv_command()`` (which can't happen
        while ``agent.run_turn()`` blocks the main thread)."""
        try:
            from .. import ui as _ui

            _ui._deliver_confirm_reply(cmd.request_id, cmd.accepted)
        except Exception as e:  # noqa: BLE001
            logger.warning("confirm reply dispatch failed: %s", e)

    def _dispatch_ask_question_reply(self, cmd: AskQuestionReplyCommand) -> None:
        """Same side-channel pattern as ConfirmReply — the agent
        thread is blocked inside ``AskUserQuestion`` waiting for
        this exact reply by request_id. Queueing through
        ``_cmd_queue`` would deadlock (REPL loop is blocked too)."""
        try:
            from ..tools import ask as _ask

            _ask._deliver_question_reply(cmd.request_id, cmd.answers, cmd.cancelled)
        except Exception as e:  # noqa: BLE001
            logger.warning("ask_question reply dispatch failed: %s", e)

    def _parse_frame(self, line: str) -> Command | None:
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("TUI sent unparseable line: %s", line[:200])
            return None
        if not isinstance(frame, dict):
            return None
        method = str(frame.get("method") or "")
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        cmd = command_from_json_rpc(method, params)
        if cmd is None:
            # Reply with METHOD_NOT_FOUND only when the frame has
            # an ``id`` (i.e. it's a request, not a notification).
            frame_id = frame.get("id")
            if frame_id is not None:
                self._send_error(
                    frame_id,
                    _ERR_METHOD_NOT_FOUND,
                    f"unknown method: {method!r}",
                )
            return None
        return cmd

    def _send_error(self, frame_id: Any, code: int, message: str) -> None:
        if self._conn is None or self._socket_dead:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": frame_id,
            "error": {"code": code, "message": message},
        }
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with self._write_lock:
            conn = self._conn
            if conn is None:
                # Conn already torn down — nothing to send. Mark
                # dead so future frames don't try either.
                self._socket_dead = True
                return
            try:
                conn.sendall(line)
            except (BrokenPipeError, OSError):
                # Error replies are best-effort; mark dead so we
                # don't keep trying on every subsequent frame.
                self._socket_dead = True


def _strip_type(d: dict[str, Any]) -> dict[str, Any]:
    """JSON-RPC ``method`` already carries the event type; the
    nested ``type`` field in ``params`` would be redundant.
    Drop it to keep frames small."""
    return {k: v for k, v in d.items() if k != "type"}
