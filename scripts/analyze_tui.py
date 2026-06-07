"""Drive the Ink TUI through a realistic session, capture its
ANSI-rendered output, and produce both raw and stripped views
so we can inspect what users actually see in the terminal."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import json

from athena.config import Config
from athena.tui_gateway.banner_data import build_banner
from athena.tui_gateway.events import (
    MessageAppendEvent,
    StatusUpdateEvent,
    StreamDeltaEvent,
    StreamEndEvent,
    StreamStartEvent,
    ToolCompleteEvent,
    ToolStartEvent,
)
from athena.tui_gateway.server import _locate_bundle, _strip_type


def _send(conn, evt) -> None:
    frame = {
        "jsonrpc": "2.0",
        "method": evt.type,
        "params": _strip_type(asdict(evt)),
    }
    conn.sendall((json.dumps(frame) + "\n").encode("utf-8"))


def main() -> None:
    cols = int(sys.argv[1]) if len(sys.argv) > 1 else 130
    rows = int(sys.argv[2]) if len(sys.argv) > 2 else 40

    bundle = _locate_bundle()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    listener.settimeout(5.0)

    env = os.environ.copy()
    env["ATHENA_TUI_PORT"] = str(port)
    env["COLUMNS"] = str(cols)
    env["LINES"] = str(rows)
    env["FORCE_COLOR"] = "1"

    raw_path = Path("/tmp/tui_analyze.raw")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    capture = raw_path.open("wb")
    proc = subprocess.Popen(
        ["node", str(bundle)],
        stdin=subprocess.DEVNULL,
        stdout=capture,
        stderr=capture,
        env=env,
    )

    try:
        conn, _ = listener.accept()
        cfg = Config()
        # 1. Cold-start banner.
        _send(conn, build_banner(
            model="troofevades-q35:athena",
            cwd=Path(__file__).resolve().parents[1],
            cfg=cfg,
        ))
        _send(conn, StatusUpdateEvent(
            model="troofevades-q35:athena",
            profile="default",
            elapsed_seconds=0.0,
            tokens_up=0,
            tokens_down=0,
        ))
        time.sleep(0.4)
        # 2. First user turn.
        _send(conn, MessageAppendEvent(
            role="user",
            content="explain how the gateway protocol works",
        ))
        # 3. Streaming response (with <think> block + markdown).
        sid = "s1"
        _send(conn, StreamStartEvent(stream_id=sid))
        chunks = [
            "<think>\nWalking through the architecture...\n</think>\n\n",
            "The **gateway protocol** is line-delimited JSON-RPC 2.0 over",
            " a TCP loopback socket. Each frame has the shape:\n\n",
            "```json\n",
            "{\"jsonrpc\":\"2.0\",\"method\":\"banner\",\"params\":{...}}\n",
            "```\n\n",
            "Two directions:\n",
            "- **gateway → TUI**: events (banner, message.append, etc)\n",
            "- **TUI → gateway**: commands (user.input, confirm.reply)\n",
        ]
        for c in chunks:
            _send(conn, StreamDeltaEvent(stream_id=sid, text=c))
            time.sleep(0.05)
        _send(conn, StreamEndEvent(stream_id=sid))
        # 4. Tool call.
        _send(conn, ToolStartEvent(
            call_id="t1", tool="Read",
            args_preview="file_path=athena/tui_gateway/server.py",
        ))
        time.sleep(0.3)
        _send(conn, ToolCompleteEvent(
            call_id="t1", tool="Read", ok=True,
            result_preview="200 lines from server.py",
        ))
        # 5. Status update.
        _send(conn, StatusUpdateEvent(
            model="troofevades-q35:athena",
            profile="default",
            elapsed_seconds=12.4,
            tokens_up=1834,
            tokens_down=412,
            tool_summary="Read 1",
        ))
        time.sleep(0.4)
        # 6. Second turn.
        _send(conn, MessageAppendEvent(role="user", content="and the silencing layers?"))
        sid2 = "s2"
        _send(conn, StreamStartEvent(stream_id=sid2))
        for c in [
            "Three layers, stacked:\n",
            "1. ``console._file = None`` → Rich resolves sys.stdout at call time\n",
            "2. ``sys.stdout = _NullStream`` → catches print()\n",
            "3. ``os.dup2(devnull, 1)`` → catches native fd-1 writes\n",
        ]:
            _send(conn, StreamDeltaEvent(stream_id=sid2, text=c))
            time.sleep(0.05)
        _send(conn, StreamEndEvent(stream_id=sid2))
        time.sleep(0.5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        capture.close()
        listener.close()

    # Strip ANSI for human-readable inspection.
    ansi_re = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b\(.")
    raw = raw_path.read_bytes()
    plain = ansi_re.sub("", raw.decode("utf-8", errors="replace"))
    plain_path = Path("/tmp/tui_analyze.plain")
    plain_path.write_text(plain, encoding="utf-8")
    # Get LAST screenful only — Ink re-emits the whole frame on
    # each update, so the last is what stays on screen.
    lines = plain.splitlines()
    print(f"captured {raw_path.stat().st_size} raw bytes / {len(plain)} stripped chars")
    print(f"plain text: {plain_path}\n")
    print("=" * cols)
    for line in lines[-min(rows, len(lines)):]:
        print(line)
    print("=" * cols)


if __name__ == "__main__":
    main()
