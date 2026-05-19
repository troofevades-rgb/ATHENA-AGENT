"""/resume — load a saved session transcript into the current agent."""

from __future__ import annotations

import json
from pathlib import Path

from .. import ui
from ..config import SESSIONS_DIR
from . import command


@command("resume")
def cmd_resume(agent, arg: str = "") -> str:
    arg = arg.strip()
    if not arg:
        # List the most recent sessions
        sessions = sorted(
            SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if not sessions:
            ui.info(f"no sessions in {SESSIONS_DIR}")
            return ""
        ui.info("recent sessions (use `/resume <filename>`):")
        for p in sessions[:10]:
            ui.console.print(f"  • {p.name}  ({p.stat().st_size} bytes)")
        return ""
    p = Path(arg).expanduser()
    if not p.exists():
        # Try treating it as a session in SESSIONS_DIR
        p = SESSIONS_DIR / arg
        if not p.exists():
            ui.error(f"session not found: {arg}")
            return ""
    try:
        msgs = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        ui.error(f"failed to load {p}: {e}")
        return ""
    if not isinstance(msgs, list):
        ui.error("session file is not a list of messages")
        return ""
    # Keep our system prompt; replace the rest with the saved messages (skip its system)
    system = agent.messages[0]
    rest = [m for m in msgs if m.get("role") != "system"]
    agent.messages = [system] + rest
    ui.info(f"resumed {p.name}: {len(rest)} messages")
    return ""
