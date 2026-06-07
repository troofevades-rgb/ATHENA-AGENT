"""Sub-agent dispatch — Claude Code's `Agent` tool.

A sub-agent is spawned by calling :py:meth:`Agent.fork` on the live parent
agent. The fork inherits the parent's runtime (model, ollama host) but runs on
a daemon thread with a scoped tool set, an injected system addendum, and the
``AUTO_DENY`` approval callback so it cannot deadlock waiting on a prompt.

Available subagent types:
- general-purpose: full tool set
- Explore: read-only — Read/Glob/Grep/WebFetch/WebSearch only
- Plan: planning-only — read-only tools, asked to produce a step-by-step plan
"""

from __future__ import annotations

from typing import Any

from .. import ui
from .registry import _REGISTRY, _TOOLSETS, tool

# Read-only scope shared by Explore and Plan. Tool *names* (not toolsets)
# because the "file" toolset includes Write/Edit, which read-only forks should
# not see.
_READONLY_TOOL_NAMES: set[str] = {
    "Read",
    "read_file",
    "Glob",
    "glob",
    "Grep",
    "grep",
    "WebFetch",
    "web_fetch",
    "WebSearch",
    "web_search",
    "list_dir",
}


SUBAGENT_TYPES: dict[str, dict[str, Any]] = {
    "general-purpose": {
        "description": "General-purpose agent for complex multi-step research and tasks. Has access to the full tool set.",
        "enabled_toolsets": None,  # None → all registered toolsets
        "disabled_tools": None,
        "system_addendum": (
            "You are a sub-agent. Run the task to completion and return a single "
            "concise final message summarizing what you did and what you found. "
            "Do not ask the user for clarification — make reasonable judgment calls."
        ),
    },
    "Explore": {
        "description": "Read-only search agent for locating code, files, and answering 'where is X' questions.",
        "enabled_toolsets": ["file", "web"],
        "disabled_tools": "readonly",  # sentinel: subtract everything not in _READONLY_TOOL_NAMES
        "system_addendum": (
            "You are an Explore sub-agent. You have READ-ONLY tools. Locate code, "
            "files, or symbols and report findings concisely. Do not propose edits "
            "or changes. Return the most relevant file paths with line numbers."
        ),
    },
    "Plan": {
        "description": "Planning agent that produces a step-by-step implementation plan without making changes.",
        "enabled_toolsets": ["file", "web"],
        "disabled_tools": "readonly",
        "system_addendum": (
            "You are a Plan sub-agent. You have READ-ONLY tools. Investigate enough "
            "to produce a concrete implementation plan: which files to touch, what to "
            "change, in what order, and what could go wrong. Return ONLY the plan."
        ),
    },
}


def _resolve_disabled(spec_disabled: Any, enabled: list[str] | None) -> list[str] | None:
    """Translate a SUBAGENT_TYPES disabled_tools spec to a concrete list."""
    if spec_disabled is None:
        return None
    if spec_disabled == "readonly":
        # Subtract anything in the candidate toolsets that isn't read-only.
        candidates: set[str]
        if enabled is None:
            candidates = set(_REGISTRY.keys())
        else:
            candidates = set()
            for ts in enabled:
                candidates |= _TOOLSETS.get(ts, set())
        return sorted(candidates - _READONLY_TOOL_NAMES)
    if isinstance(spec_disabled, (list, tuple, set)):
        return list(spec_disabled)
    return None


@tool(
    name="Agent",
    toolset="agent",
    description=(
        "Launch a sub-agent to handle a complex task. Each agent type has "
        "specific capabilities. Use general-purpose for open-ended research "
        "spanning many files. Use Explore for fast read-only code lookups. "
        "Use Plan to draft an implementation plan without making changes.\n\n"
        "Brief the sub-agent like a colleague who just walked in: state the "
        "goal, what you've ruled out, and what form of report you want. "
        "Self-contained prompts produce better results than terse commands."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The full task brief for the sub-agent."},
            "description": {
                "type": "string",
                "description": (
                    "Optional short (3-5 word) display label. If omitted, "
                    "auto-derived from the first line of ``prompt``."
                ),
            },
            "subagent_type": {
                "type": "string",
                "enum": list(SUBAGENT_TYPES.keys()),
                "description": "Which kind of sub-agent to spawn. Defaults to general-purpose.",
            },
        },
        "required": ["prompt"],
    },
)
def Agent(
    prompt: str,
    description: str = "",
    subagent_type: str = "general-purpose",
) -> str:
    # ``description`` was previously required, but it's a display-only
    # label — smaller models routinely drop it and got a TypeError back
    # with no clean recovery path. Auto-derive when missing: take the
    # first non-empty line, trim to ~60 chars.
    if not description.strip():
        first_line = next(
            (line.strip() for line in prompt.splitlines() if line.strip()),
            "sub-agent task",
        )
        description = first_line[:60] + ("…" if len(first_line) > 60 else "")
    spec = SUBAGENT_TYPES.get(subagent_type)
    if not spec:
        return f"ERROR: unknown subagent_type {subagent_type!r}"

    # Lazy to avoid circular import at module load.
    from ..agent import get_current_agent

    parent = get_current_agent()
    if parent is None:
        return "ERROR: Agent tool can only be called from within a running agent turn"

    enabled = spec["enabled_toolsets"]
    if enabled is None:
        # General-purpose: enumerate all toolsets so fork() always receives a list.
        enabled = sorted(_TOOLSETS.keys())
    disabled = _resolve_disabled(spec["disabled_tools"], spec["enabled_toolsets"])

    ui.info(f"spawning sub-agent: {subagent_type} — {description}")
    try:
        from ..agent.fork import fork as _fork
        from ..provenance import SUBAGENT

        # ``Agent.fork`` is monkey-patched onto the class at module load
        # (see ``athena.agent.core``), so mypy can't see it as a method.
        # Call the underlying typed function directly — identical at
        # runtime to ``parent.fork(...)``.
        result = _fork(
            parent,
            enabled_toolsets=enabled,
            disabled_tools=disabled,
            system_addendum=spec["system_addendum"],
            user_prompt=prompt,
            quiet=False,  # surface tool calls in the parent's terminal
            # Distinct origin so the TUI surfaces the sub-agent's tool
            # calls (nested + dimmed) instead of suppressing them like the
            # silent curator / review forks. Its streaming prose stays
            # suppressed — only the tool activity shows.
            write_origin=SUBAGENT,
        )
    except Exception as e:
        return f"ERROR running sub-agent: {e}"

    if result.error:
        return f"ERROR running sub-agent: {result.error}"
    return result.final_response or "(no assistant response)"
