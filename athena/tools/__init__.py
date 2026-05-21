"""Tool implementations. Importing this module registers all tools.

Tool naming follows Claude Code conventions (Read/Edit/Write/Bash/Glob/Grep/
WebFetch/WebSearch/Agent/TaskCreate/etc.). Old snake_case names remain as
aliases for back-compat.
"""

from . import (
    agent_tool,  # Agent (sub-agents)
    ask,  # AskUserQuestion
    clarify,  # clarify (T2-08)
    diagnose,  # Diagnose (T5-03R)
    file_ops,  # Read, Write, Edit, list_dir
    memory_tools,  # write_memory, list_memories, delete_memory
    patch_apply,  # patch_apply (T2-07)
    plan,  # ExitPlanMode, EnterPlanMode
    read_tool_result,  # read_tool_result (T2-06)
    recall_tools,  # search_sessions
    search,  # Glob, Grep
    shell,  # Bash, bash_output, kill_bash
    skill_tools,  # skills_list, skill_view, skill_manage
    task,  # TaskCreate, TaskUpdate, TaskList
    web,  # WebFetch, WebSearch
)

# T6-02: search_x lives under athena.social — importing it
# here is what registers the tool on agent startup.
from ..social import search as _social_search_register  # noqa: F401

# T6-03: delegate_to_cli lives under athena.delegate.
from ..delegate import cli as _delegate_register  # noqa: F401

from .registry import all_tools, dispatch, get_tool, ollama_schema, tool

__all__ = ["all_tools", "dispatch", "get_tool", "ollama_schema", "tool"]
