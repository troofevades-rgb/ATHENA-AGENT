"""``/models`` — list models available on the active provider."""

from __future__ import annotations

from typing import Any

from .. import ui
from . import command


@command("models")
def cmd_models(agent: Any, arg: str = "") -> str:
    try:
        names = agent.provider.list_models()
    except Exception as e:
        ui.error(f"could not list models: {e}")
        return ""
    for n in names:
        marker = "*" if n == agent.model else " "
        ui.console.print(f" {marker} {n}")
    return ""
