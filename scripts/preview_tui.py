"""Spawn the Ink TUI with a synthesized banner/status, capture
its actual rendered output to a file, and strip ANSI for visual
inspection. Lets me debug layout without asking the user to
take a screenshot every time."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from athena.config import Config
from athena.tui_gateway.banner_data import build_banner
from athena.tui_gateway.events import (
    MessageAppendEvent,
    StatusUpdateEvent,
    ToolStartEvent,
)
from athena.tui_gateway.server import _locate_bundle, _strip_type
import json
from dataclasses import asdict


def _send(conn: socket.socket, event_obj) -> None:
    frame = {
        "jsonrpc": "2.0",
        "method": event_obj.type,
        "params": _strip_type(asdict(event_obj)),
    }
    conn.sendall((json.dumps(frame) + "\n").encode("utf-8"))


def render_preview(cols: int, rows: int, out_path: Path) -> None:
    # Bind port, spawn bundle pointed at it.
    bundle = _locate_bundle()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    listener.settimeout(5.0)

    env = os.environ.copy()
    env["ATHENA_TUI_PORT"] = str(port)
    # Force the terminal size the bundle reports via stdout.columns.
    env["COLUMNS"] = str(cols)
    env["LINES"] = str(rows)
    env["FORCE_COLOR"] = "1"

    captured = out_path.open("wb")
    proc = subprocess.Popen(
        ["node", str(bundle)],
        stdin=subprocess.DEVNULL,
        stdout=captured,  # Ink renders to "stdout" but we routed
        stderr=captured,  # it to stderr; capture both anyway.
        env=env,
    )

    try:
        conn, _ = listener.accept()
        # Banner first.
        cfg = Config()
        banner = build_banner(
            model="troofevades-q35:athena",
            cwd=Path("C:/Users/mtt_j/projects/ocodev2"),
            cfg=cfg,
        )
        _send(conn, banner)
        # A few transcript lines so we see the "after first turn"
        # collapsed-banner state, not just the cold splash.
        _send(conn, MessageAppendEvent(role="user", content="hello"))
        _send(conn, MessageAppendEvent(role="assistant", content="Hi! How can I help?"))
        _send(conn, ToolStartEvent(
            call_id="t1", tool="Read", args_preview="file=foo.py",
        ))
        _send(conn, StatusUpdateEvent(
            model="troofevades-q35:athena",
            profile="default",
            elapsed_seconds=42.5,
            tokens_up=1234,
            tokens_down=5678,
            tool_summary="Read 1 / Edit 2",
        ))
        # Let Ink render a few frames.
        time.sleep(1.5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        captured.close()
        listener.close()

    print(f"captured {out_path.stat().st_size} bytes to {out_path}")


def strip_ansi(b: bytes) -> str:
    text = b.decode("utf-8", errors="replace")
    # Drop terminal capabilities + color codes for the readable
    # version. Keep newlines.
    ansi_re = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b\(.")
    text = ansi_re.sub("", text)
    # Collapse cursor-movement sequences that print blank space.
    return text


if __name__ == "__main__":
    cols = int(sys.argv[1]) if len(sys.argv) > 1 else 130
    rows = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    raw = Path("/tmp/tui_raw.bin")
    render_preview(cols, rows, raw)
    plain = strip_ansi(raw.read_bytes())
    plain_path = Path("/tmp/tui_plain.txt")
    plain_path.write_text(plain, encoding="utf-8")
    print(f"plain text → {plain_path} ({len(plain)} chars)")
    # Print last screenful (Ink emits many incremental frames;
    # the last is what stays visible).
    lines = plain.splitlines()
    print("\n--- last 60 lines ---")
    for line in lines[-60:]:
        print(line)
