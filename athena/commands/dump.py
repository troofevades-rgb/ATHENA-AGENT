"""``/dump`` — print the live system prompt for debugging."""

from __future__ import annotations

from typing import Any

from .. import ui
from . import command


@command("dump")
def cmd_dump(agent: Any, arg: str = "") -> str:
    sysmsg = next((m for m in agent.messages if m.get("role") == "system"), None)
    if not sysmsg:
        ui.error("no system message in history")
        return ""
    content = sysmsg.get("content", "")
    ui.info(f"system prompt: {len(content):,} chars / ~{len(content) // 4:,} tokens")
    ui.console.print(content, soft_wrap=True, highlight=False)
    return ""
