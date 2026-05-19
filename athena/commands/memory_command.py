"""/memory — list, view, or delete persistent memories from the REPL."""

from __future__ import annotations

from .. import ui
from ..memory import (
    delete_memory,
    list_memories,
    memory_dir,
    parse_memory_file,
)
from . import command


@command("memory")
def cmd_memory(agent, arg: str = "") -> str:
    arg = arg.strip()
    sub, _, rest = arg.partition(" ")

    if not sub or sub == "list":
        mems = list_memories(agent.workspace)
        if not mems:
            ui.info(f"no memories at {memory_dir(agent.workspace)}")
            return ""
        ui.console.print(f"[dim]dir: {memory_dir(agent.workspace)}[/]")
        for mf in mems:
            ui.console.print(f"  [bold]{mf.path.name}[/]  [dim][{mf.type}][/]  {mf.name}")
            if mf.description:
                ui.console.print(f"    [dim]{mf.description}[/]")
        return ""

    if sub == "show":
        if not rest:
            ui.error("usage: /memory show <filename>")
            return ""
        path = memory_dir(agent.workspace) / rest
        mf = parse_memory_file(path)
        if not mf:
            ui.error(f"not found or unparseable: {path}")
            return ""
        ui.console.print(f"[bold]{mf.path.name}[/]  [dim][{mf.type}][/]")
        ui.console.print(f"  name: {mf.name}")
        ui.console.print(f"  description: {mf.description}")
        ui.console.print()
        ui.console.print(mf.body)
        return ""

    if sub == "delete":
        if not rest:
            ui.error("usage: /memory delete <filename>")
            return ""
        if delete_memory(agent.workspace, rest):
            ui.info(f"deleted {rest}")
        else:
            ui.error(f"not found: {rest}")
        return ""

    if sub == "dir":
        ui.console.print(str(memory_dir(agent.workspace)))
        return ""

    ui.error(f"unknown subcommand: {sub}. try: /memory [list|show <file>|delete <file>|dir]")
    return ""
