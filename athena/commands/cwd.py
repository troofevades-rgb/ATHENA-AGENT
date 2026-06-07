"""``/cwd [path]`` — show or change the agent's workspace.

Switching workspaces:
1. Validates the path is a directory.
2. Updates ``agent.workspace`` and ``tools.file_ops`` workspace
   (which delegates to ``path_security`` per T1-07).
3. Reconfigures the ShellHookPlugin so workspace-local
   ``settings.json`` hooks are re-read from the new path.
4. Rebuilds the system prompt in place so ATHENA.md / MEMORY.md
   reflect the new workspace. Conversation history is preserved
   — use ``/clear`` if you want a reset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import tools, ui
from . import command


@command("cwd")
def cmd_cwd(agent: Any, arg: str = "") -> str:
    if not arg:
        ui.info(f"workspace: {agent.workspace}")
        return ""
    new = Path(arg).expanduser().resolve()
    if not new.is_dir():
        ui.error(f"not a directory: {new}")
        return ""
    agent.workspace = new
    tools.file_ops.set_workspace(new, max_read=agent.cfg.max_file_read)
    agent._configure_shell_hook_plugin()
    if agent.messages and agent.messages[0].get("role") == "system":
        agent.messages[0] = {"role": "system", "content": agent._build_system()}
    ui.info(f"workspace -> {new} (system prompt rebuilt; /clear to reset history)")
    return ""
