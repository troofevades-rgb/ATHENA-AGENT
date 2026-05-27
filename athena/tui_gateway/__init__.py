"""Bridge between the Python agent and the Ink-based TUI subprocess.

Architecture (Hermes-style split):

  athena CLI (Python)              ui-tui (TypeScript / Ink / React)
  ─────────────────                ──────────────────────────────────
  athena/__main__.py        ←──    spawns node dist/main.js
  athena/tui_gateway/       ←──    line-delimited JSON-RPC 2.0
      server.py             ──→    stdin (events)
      events.py             ←──    stdout (commands)
      protocol.py
                                   stderr left free for TUI logs

Why split: a single source of truth for UI state lives in Python,
and the same event stream can later feed a web dashboard
(FastAPI + xterm.js or React) without changing any agent code.

Public surface (kept minimal in Phase 1):

  TuiGateway.start()          spawn the TUI subprocess
  TuiGateway.send_event(evt)  push a notification to the TUI
  TuiGateway.recv_command()   block until the TUI sends a command
  TuiGateway.close()          shut down cleanly

Phase 1.2 scope: protocol + gateway server. Spawning is wired in
Phase 1.4 when ``athena/__main__.py`` switches over.
"""

from __future__ import annotations

from .events import (
    BannerEvent,
    Event,
    ExitEvent,
    MessageAppendEvent,
    StatusUpdateEvent,
    StreamDeltaEvent,
    StreamEndEvent,
    StreamStartEvent,
    ThemeChangeEvent,
    ToolCompleteEvent,
    ToolProgressEvent,
    ToolStartEvent,
)
from .server import TuiGateway

__all__ = [
    "TuiGateway",
    "Event",
    "BannerEvent",
    "MessageAppendEvent",
    "StreamStartEvent",
    "StreamDeltaEvent",
    "StreamEndEvent",
    "ToolStartEvent",
    "ToolProgressEvent",
    "ToolCompleteEvent",
    "StatusUpdateEvent",
    "ThemeChangeEvent",
    "ExitEvent",
]
