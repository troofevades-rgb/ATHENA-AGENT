"""``/hooks`` — list hooks loaded from settings.json."""

from __future__ import annotations

from .. import hooks as hooks_mod
from .. import ui
from . import command


@command("hooks")
def cmd_hooks(agent, arg: str = "") -> str:
    hs = hooks_mod.list_hooks()
    if not hs:
        ui.info("no hooks configured. drop one in ~/.athena/settings.json")
        return ""
    for h in hs:
        ui.console.print(f"  • [bold]{h.event}[/]  matcher={h.matcher!r}  -> {h.command!r}")
    return ""
