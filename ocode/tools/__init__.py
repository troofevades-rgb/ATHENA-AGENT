"""Tool implementations. Importing this module registers all tools.

Tool naming follows Claude Code conventions (Read/Edit/Write/Bash/Glob/Grep/
WebFetch/WebSearch/Agent/TaskCreate/etc.). Old snake_case names remain as
aliases for back-compat.
"""
from . import file_ops      # Read, Write, Edit, list_dir
from . import shell         # Bash, bash_output, kill_bash
from . import search        # Glob, Grep
from . import web           # WebFetch, WebSearch
from . import task          # TaskCreate, TaskUpdate, TaskList
from . import ask           # AskUserQuestion
from . import plan          # ExitPlanMode, EnterPlanMode
from . import memory_tools  # write_memory, list_memories, delete_memory
from . import skill_tools   # skills_list, skill_view, skill_manage
from . import recall_tools  # search_sessions
from . import agent_tool    # Agent (sub-agents)

from .registry import all_tools, dispatch, get_tool, ollama_schema, tool

__all__ = ["all_tools", "dispatch", "get_tool", "ollama_schema", "tool"]
