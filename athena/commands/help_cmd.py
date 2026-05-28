"""``/help`` — print the slash-command reference."""

from __future__ import annotations

from .. import ui
from . import command

SLASH_HELP = """\
/help                show this message
/model NAME          switch model
/models              list available Ollama models
/tools               list registered tools (built-in + MCP)
/mcp                 list connected MCP servers and their tool counts
/mcp logs NAME       show recent stderr from an MCP server
/clear               reset conversation (keeps system prompt)
/cost                show token usage and elapsed time for this session
/status              show session snapshot (model, tokens, rate limits, retries)
/save [file]         save transcript (default: ~/.athena/sessions/<timestamp>.json)
/dump                print the current system prompt (what the model sees)
/cwd [path]          show or change workspace
/init                generate ATHENA.md from a workspace survey
/review [ref]        review pending changes (or a git ref)
/security-review     security-focused review of pending changes
/loop INTERVAL CMD   re-run a prompt or slash command on a timer
/loop-stop           stop a running /loop
/checkpoint [name]   snapshot the workspace + agent state
/checkpoints         list checkpoints in this session
/compact             summarize history and replace it with the summary
/resume [file]       resume a saved session transcript
/memory [list|show|delete|dir]  inspect or edit persistent memory
/plan [prompt]       enter plan mode (read-only investigation)
/plan-exit           leave plan mode without executing
/steer MSG           queue MSG; delivered before your next prompt
/steer clear         drop every pending steer for this session
/queue               list pending steers
/goal [MSG|pause|resume|status|clear]
                     set / pause / resume / inspect / clear the active goal
                     (quality-gated: refuses too-short or vague text)
/subgoal MSG         append a subgoal to the active goal
/subgoal done        mark the first not-done subgoal complete
/board [goal:<id>]   render the kanban for this workspace
/board clear         wipe every live task in the store
/computer            show computer-use status (backend, mode, allow/deny)
/video               show registered video backends + auth status
/video set NAME      pin a video backend for this session
/video list          name-only listing
/video clear         unset selector (broker auto-picks)
/theme               show TUI color palette + every registered theme
/theme set NAME      switch palette: phosphor/dusk/nord/dracula/synthwave/cyber
/theme save          persist active theme to ~/.athena/config.toml
/hooks               list configured hooks
/exit                quit
"""


@command("help")
def cmd_help(agent, arg: str = "") -> str:
    ui.console.print(SLASH_HELP)
    return ""
