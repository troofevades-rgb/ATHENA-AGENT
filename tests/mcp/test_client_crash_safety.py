"""Client-side crash-safety tests for ``MCPStdioClient``.

The existing tests/mcp/test_stdio_transport.py covers SERVER-side
behavior (the server reads a line, dispatches, writes a response).
What's not covered: the CLIENT side of the wire — what
``MCPStdioClient`` does when the subprocess misbehaves.

Production failure modes worth pinning:

1. Server crashes mid-handshake. ``initialize()`` must raise, not hang.
2. Server crashes between request-sent and response-received. The
   pending Future at client.py:166 must be woken with MCPError (the
   ``finally`` block at client.py:213-219 is supposed to do this).
3. Server NEVER responds (alive but ignoring). request() must respect
   its timeout and raise MCPError, freeing the slot.
4. Server emits malformed JSON. Client must drain it as ``[stdout-junk]``
   and keep the connection alive.
5. close() is idempotent and doesn't deadlock the parent.

If any of these regress, the user sees the symptom as a frozen REPL
("athena is thinking forever"), with the actual cause buried in a
daemon thread.
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from athena.mcp.client import MCPError, MCPStdioClient


def _server_script(tmp_path: Path, body: str) -> Path:
    """Write a tiny Python MCP-shaped stdio server and return its path."""
    src = textwrap.dedent(body)
    path = tmp_path / "mock_server.py"
    path.write_text(src, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Subprocess crash → pending request woken
# ---------------------------------------------------------------------------


def test_server_exits_before_response_wakes_pending_request(
    tmp_path: Path,
) -> None:
    """Server reads a request line then exits cleanly without
    responding. The client's pending Future must be woken with
    MCPError quickly — not hang to the 60s default timeout.

    This is the contract that client.py:213-219 promises (the
    ``finally`` block in _read_loop wakes all pending futures
    when stdout closes). Test it directly."""
    body = """\
        import sys
        # Read one request, then exit without responding.
        sys.stdin.readline()
        sys.exit(0)
    """
    script = _server_script(tmp_path, body)
    client = MCPStdioClient(
        name="crasher", command=sys.executable, args=[str(script)],
        request_timeout=5.0,
    )
    try:
        t0 = time.perf_counter()
        with pytest.raises(MCPError) as ei:
            client.request("initialize", {"protocolVersion": "2024-11-05"})
        elapsed = time.perf_counter() - t0
        # Should resolve well under the 5s timeout — the read loop
        # detects EOF and wakes the future immediately.
        assert elapsed < 2.0, (
            f"pending request took {elapsed:.2f}s to wake after server "
            f"exited; expected < 2s. The _read_loop finally block at "
            f"client.py:213-219 may have regressed."
        )
        assert "exited" in str(ei.value).lower() or "broken" in str(ei.value).lower(), (
            f"error message doesn't surface the crash: {ei.value}"
        )
    finally:
        client.close()


def test_server_crashes_with_nonzero_exit_still_wakes_pending(
    tmp_path: Path,
) -> None:
    """Same as above but the server crashes with an error exit
    code — must still wake the pending request (not orphan the
    Future)."""
    body = """\
        import sys
        sys.stdin.readline()
        sys.stderr.write("simulated panic\\n")
        sys.exit(99)
    """
    script = _server_script(tmp_path, body)
    client = MCPStdioClient(
        name="panicker", command=sys.executable, args=[str(script)],
        request_timeout=5.0,
    )
    try:
        with pytest.raises(MCPError):
            client.request("anything", timeout=3.0)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Server alive but unresponsive → timeout fires, slot is freed
# ---------------------------------------------------------------------------


def test_unresponsive_server_request_respects_timeout(
    tmp_path: Path,
) -> None:
    """Server reads requests and silently discards them — never
    responds. The client's per-request timeout must fire and free
    the pending slot so future requests can use new IDs.

    This validates client.py:170-173 (FutTimeout handler removes
    the entry from self._pending)."""
    body = """\
        import sys, time
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            # discard and continue — never respond
    """
    script = _server_script(tmp_path, body)
    client = MCPStdioClient(
        name="silent", command=sys.executable, args=[str(script)],
        request_timeout=1.0,
    )
    try:
        t0 = time.perf_counter()
        with pytest.raises(MCPError) as ei:
            client.request("ping", timeout=1.0)
        elapsed = time.perf_counter() - t0
        # Must respect the 1s timeout
        assert 0.9 < elapsed < 2.5, (
            f"request did not respect 1s timeout; took {elapsed:.2f}s"
        )
        assert "timeout" in str(ei.value).lower()
        # Slot must be freed — pending dict empty
        assert len(client._pending) == 0, (
            "timed-out request left orphan entry in _pending; "
            "long-running session would leak slots"
        )
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Malformed server output → connection stays alive
# ---------------------------------------------------------------------------


def test_malformed_server_output_does_not_kill_client(
    tmp_path: Path,
) -> None:
    """Server emits a junk line (not JSON), then a valid response.
    The client must drain the junk to stderr_lines and still
    deliver the valid response. This validates client.py:204-211."""
    body = """\
        import sys, json
        # Emit junk line first
        sys.stdout.write("not json at all\\n")
        sys.stdout.flush()
        # Then read a request and answer it correctly
        line = sys.stdin.readline()
        msg = json.loads(line)
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"ok": True}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
        # Stay alive so the response isn't racing EOF
        import time; time.sleep(2.0)
    """
    script = _server_script(tmp_path, body)
    client = MCPStdioClient(
        name="junker", command=sys.executable, args=[str(script)],
        request_timeout=3.0,
    )
    try:
        result = client.request("ping", timeout=3.0)
        assert result == {"ok": True}
        # Junk landed in stderr_lines for diagnostics
        tail = client.stderr_tail(n=20)
        assert any("not json" in line for line in tail), (
            f"junk line not surfaced for diagnostics; tail={tail}"
        )
    finally:
        client.close()


# ---------------------------------------------------------------------------
# close() idempotency and post-close behavior
# ---------------------------------------------------------------------------


def test_close_is_idempotent_and_does_not_hang(tmp_path: Path) -> None:
    """Calling close() twice in a row must not raise and must not
    block. The agent's teardown calls close() on every registered
    MCP client during shutdown; one client raising would leave the
    rest open."""
    body = """\
        import sys, time
        time.sleep(10)  # outlive the test
    """
    script = _server_script(tmp_path, body)
    client = MCPStdioClient(
        name="sleeper", command=sys.executable, args=[str(script)],
    )
    t0 = time.perf_counter()
    client.close()
    client.close()  # second call must be a no-op
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, (
        f"double-close took {elapsed:.2f}s; close() is not bounded"
    )
    # Process is reaped
    assert not client.is_alive()


def test_request_after_close_raises_not_hangs(tmp_path: Path) -> None:
    """A request issued after close() must fail fast (broken pipe),
    not hang waiting for a response that will never come."""
    body = """\
        import sys, time
        time.sleep(10)
    """
    script = _server_script(tmp_path, body)
    client = MCPStdioClient(
        name="closed", command=sys.executable, args=[str(script)],
        request_timeout=3.0,
    )
    client.close()
    t0 = time.perf_counter()
    with pytest.raises(MCPError):
        client.request("anything", timeout=2.0)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.5, (
        f"post-close request hung {elapsed:.2f}s instead of failing fast"
    )


# ---------------------------------------------------------------------------
# Spawn failure: missing command
# ---------------------------------------------------------------------------


def test_missing_command_raises_mcperror_not_filenotfound() -> None:
    """``MCPStdioClient(...)`` for a nonexistent binary must raise
    MCPError so callers can pattern-match a single exception type,
    not FileNotFoundError (which leaks subprocess internals)."""
    with pytest.raises(MCPError) as ei:
        MCPStdioClient(
            name="ghost",
            command="this-binary-does-not-exist-anywhere-promise",
        )
    assert "not found" in str(ei.value).lower()
