"""Phase 18.2 stage 1 -- ``Tool.parallel_safe`` field + flag rollout.

Pins:
  - The ``Tool`` dataclass declares ``parallel_safe: bool`` with a
    default of ``False`` (conservative -- opt-in per tool).
  - The ``@tool(...)`` decorator forwards a ``parallel_safe=`` kwarg
    onto the registered :class:`Tool`.
  - Every tool the stage 1 commit flagged actually carries the flag
    (catches an accidental rebase loss).
  - Every confirmation-required tool stays serial (the prompt
    serializes naturally; never flag these as parallel).
  - The stage-1 list of serial-by-design tools (browser session,
    computer screen, plan-mode mutators, etc.) stays serial.
"""

from __future__ import annotations

from athena import tools
from athena.tools.registry import Tool, tool


# ---------------------------------------------------------------------------
# Tool dataclass + @tool decorator carry the field
# ---------------------------------------------------------------------------


def test_tool_dataclass_defaults_to_serial() -> None:
    """A freshly-constructed Tool has ``parallel_safe=False`` by default
    -- new tools are conservative until opted in."""
    t = Tool(
        name="x",
        description="d",
        parameters={"type": "object", "properties": {}},
        func=lambda: "",
    )
    assert t.parallel_safe is False


def test_tool_decorator_accepts_parallel_safe_kwarg() -> None:
    """``@tool(parallel_safe=True)`` flows through to the registered
    Tool instance."""
    @tool(
        name="_pflag_test_tool",
        description="probe",
        parameters={"type": "object", "properties": {}},
        toolset="_test",
        parallel_safe=True,
    )
    def _impl() -> str:
        return "ok"

    t = tools.get_tool("_pflag_test_tool")
    assert t is not None
    assert t.parallel_safe is True


def test_tool_decorator_defaults_to_serial_when_omitted() -> None:
    """Omit ``parallel_safe`` -> Tool.parallel_safe stays False."""
    @tool(
        name="_pflag_default_tool",
        description="probe",
        parameters={"type": "object", "properties": {}},
        toolset="_test",
    )
    def _impl2() -> str:
        return "ok"

    t = tools.get_tool("_pflag_default_tool")
    assert t is not None
    assert t.parallel_safe is False


# ---------------------------------------------------------------------------
# Stage-1 rollout: the read-only surface is flagged
# ---------------------------------------------------------------------------


# Tools flagged in Phase 18.2 stage 1. Grouped by category so a
# regression jumps out at a glance. Keep alphabetised within groups.
_EXPECTED_PARALLEL_SAFE: set[str] = {
    # file (read-only)
    "Read", "Glob", "Grep", "list_dir", "workspace_info", "read_tool_result",
    # web (read-only network)
    "WebFetch", "WebSearch",
    # core / tasks
    "TaskList", "board_show",
    # diagnose
    "Diagnose",
    # memory (read-only)
    "list_memories", "memory_query",
    # recall + social search
    "search_sessions", "search_x", "lookup_x_user",
    # safety analysis
    "osv_check", "tirith_check", "url_safety_check",
    # skills (read-only)
    "skill_view", "skills_list",
    # media analysis (read input, no shared-state mutation)
    "vision_analyze", "video_analyze", "audio_analyze",
    "document_analyze", "ocr",
}


def test_stage_1_rollout_lists_match() -> None:
    """The 26 tools the stage 1 commit flagged are still flagged.
    Drift in either direction (a new tool sneaking the flag, or a
    listed tool losing it during a refactor) breaks the test so the
    parallel-dispatch contract stays auditable."""
    actually_flagged = {
        t.name
        for t in tools.all_tools()
        if t.parallel_safe and not t.name.startswith("_")
    }
    missing = _EXPECTED_PARALLEL_SAFE - actually_flagged
    extra = actually_flagged - _EXPECTED_PARALLEL_SAFE
    assert not missing, f"flag dropped on tools: {sorted(missing)}"
    assert not extra, (
        f"unexpected parallel_safe on tools: {sorted(extra)}. "
        "Audit the change against the shared-state checklist in "
        "athena/tools/registry.py:Tool.parallel_safe before adding."
    )


# ---------------------------------------------------------------------------
# Tools that MUST stay serial
# ---------------------------------------------------------------------------


def test_confirmation_required_tools_are_never_parallel_safe() -> None:
    """Every tool that opts into the confirmation prompt MUST stay
    serial -- two concurrent prompts at once would race the user's
    'allow' response and approve the wrong call."""
    bad = [
        t.name
        for t in tools.all_tools()
        if t.requires_confirmation and t.parallel_safe
    ]
    assert not bad, (
        f"confirmation-required tool(s) flagged parallel_safe: {bad}"
    )


# Stage-1 list of tools that must stay serial for documented reasons.
# A test rather than a frozenset because the categories matter for
# future readers.
_BROWSER_SESSION_TOOLS = {
    "browser_click", "browser_close", "browser_extract_links",
    "browser_extract_text", "browser_fill", "browser_get_cookies",
    "browser_navigate", "browser_screenshot", "browser_wait_for",
}
_COMPUTER_SCREEN_TOOLS = {
    "computer_click", "computer_key", "computer_observe",
    "computer_screenshot", "computer_scroll", "computer_type",
}
_STATE_MUTATORS = {
    "Agent",            # forks a child agent + threads
    "AskUserQuestion",  # interactive prompt -- must be serial
    "EnterPlanMode",    # mutates plan-mode ContextVar
    "ExitPlanMode",     # mutates plan-mode ContextVar
    "TaskCreate", "TaskUpdate",  # mutates task store
    "clarify",          # interactive prompt
    "write_memory", "delete_memory",  # memory writes
    "bash_output", "kill_bash",       # bash process state
    "delegate_to_cli",  # external process state
    "video_generate", "animate_image",  # long-running write artifacts
}


def test_browser_session_tools_stay_serial() -> None:
    """All browser_* tools share one BrowserSession (cookies, page,
    URL). Concurrent navigate + click would race; keep serial."""
    flagged = [
        n for n in _BROWSER_SESSION_TOOLS
        if (t := tools.get_tool(n)) is not None and t.parallel_safe
    ]
    assert not flagged, f"browser tools must stay serial: {flagged}"


def test_computer_screen_tools_stay_serial() -> None:
    """All computer_* tools touch the single user screen + keyboard.
    Concurrent input is meaningless; keep serial."""
    flagged = [
        n for n in _COMPUTER_SCREEN_TOOLS
        if (t := tools.get_tool(n)) is not None and t.parallel_safe
    ]
    assert not flagged, f"computer tools must stay serial: {flagged}"


def test_state_mutator_tools_stay_serial() -> None:
    """Tools that mutate shared session/task/process state must stay
    serial -- their results often gate the next call."""
    flagged = [
        n for n in _STATE_MUTATORS
        if (t := tools.get_tool(n)) is not None and t.parallel_safe
    ]
    assert not flagged, (
        f"state-mutating tools must stay serial: {flagged}"
    )
