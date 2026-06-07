"""``/tools`` — list registered tools (built-in + MCP)."""

from __future__ import annotations

from typing import Any

from .. import tools, ui
from . import command


@command("tools")
def cmd_tools(agent: Any, arg: str = "") -> str:
    for t in tools.all_tools(disabled=agent.cfg.disabled_tools):
        confirm = " [confirm]" if t.requires_confirmation else ""
        kind = " [mcp]" if "__" in t.name else ""
        ui.console.print(f"  • [bold]{t.name}[/]{kind}{confirm} — {t.description.splitlines()[0]}")
    return ""
