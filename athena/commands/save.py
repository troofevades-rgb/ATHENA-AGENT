"""``/save [path]`` — write the conversation history to a JSON file."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import ui
from ..config import SESSIONS_DIR
from . import command


@command("save")
def cmd_save(agent, arg: str = "") -> str:
    path = Path(arg).expanduser() if arg else SESSIONS_DIR / f"{int(time.time())}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agent.messages, indent=2), encoding="utf-8")
    ui.info(f"saved transcript to {path}")
    return ""
