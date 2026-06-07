"""``/hooks`` — list settings.json hooks the ShellHookPlugin loaded."""

from __future__ import annotations

from typing import Any

from .. import ui
from . import command


@command("hooks")
def cmd_hooks(agent: Any, arg: str = "") -> str:
    plugin = None
    for p in getattr(agent.plugin_hooks, "plugins", []):
        if getattr(p, "name", "") == "shell_hook":
            plugin = p
            break
    hs = list(getattr(plugin, "_hooks", []) or []) if plugin is not None else []
    if not hs:
        ui.info("no hooks configured. drop one in ~/.athena/settings.json")
        return ""
    for h in hs:
        ui.console.print(f"  • [bold]{h.event}[/]  matcher={h.matcher!r}  -> {h.command!r}")
    return ""
