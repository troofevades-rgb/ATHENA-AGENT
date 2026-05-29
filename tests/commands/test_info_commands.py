"""Tests for the read-only info slash commands.

Covers ``/help``, ``/dump``, ``/hooks``, ``/tools``, ``/models``,
``/cost``. All of these are read-only (no agent state mutation,
no disk writes), so they share a single fake-agent fixture and
ui-capture helper.

The mutating commands (``/clear``, ``/save``) live in their own
test files because they need different fixtures.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---- shared helpers -------------------------------------------------


def _capture_ui(module_path: str):
    """Patch ui.info/warn/error/console.print on the target module
    so we can assert on emitted text. Returns (lines list, list of
    context-managers to start/stop)."""
    lines: list[str] = []
    patches = []
    for fn_name in ("info", "warn", "error"):
        patches.append(
            patch(
                f"{module_path}.ui.{fn_name}",
                side_effect=lambda msg, *a, _n=fn_name, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    patches.append(
        patch(
            f"{module_path}.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _run(cmd_fn, agent, arg: str, module_path: str) -> str:
    """Invoke ``cmd_fn(agent, arg)`` with ui captured. Returns the
    captured output as a single newline-joined string."""
    lines, patches = _capture_ui(module_path)
    for p in patches:
        p.start()
    try:
        cmd_fn(agent, arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


# ---- /help ----------------------------------------------------------


def test_help_lists_every_documented_command() -> None:
    """The help block must mention every slash command users
    might type. If we add or remove a command, this test snags it."""
    from athena.commands.help import cmd_help

    out = _run(cmd_help, SimpleNamespace(), "", "athena.commands.help")
    for expected in [
        "/help", "/model", "/models", "/tools", "/mcp",
        "/clear", "/cost", "/status", "/save", "/dump",
        "/cwd", "/init", "/review", "/loop", "/checkpoint",
        "/compact", "/resume", "/memory", "/plan", "/steer",
        "/queue", "/goal", "/subgoal", "/board", "/video",
        "/theme", "/hooks", "/exit",
    ]:
        assert expected in out, f"{expected} missing from /help output"


# ---- /dump ----------------------------------------------------------


def test_dump_prints_system_prompt_with_size_summary() -> None:
    from athena.commands.dump import cmd_dump

    sysprompt = "You are athena. " * 50  # ~800 chars
    agent = SimpleNamespace(
        messages=[
            {"role": "system", "content": sysprompt},
            {"role": "user", "content": "hi"},
        ],
    )
    out = _run(cmd_dump, agent, "", "athena.commands.dump")
    # Size summary in info() — char count + ~token estimate
    assert "chars" in out
    assert "tokens" in out
    # The prompt itself should appear in the console output
    assert "athena" in out


def test_dump_errors_when_no_system_message() -> None:
    from athena.commands.dump import cmd_dump

    agent = SimpleNamespace(messages=[{"role": "user", "content": "hi"}])
    out = _run(cmd_dump, agent, "", "athena.commands.dump")
    assert "no system message" in out.lower()


def test_dump_errors_when_messages_empty() -> None:
    from athena.commands.dump import cmd_dump

    agent = SimpleNamespace(messages=[])
    out = _run(cmd_dump, agent, "", "athena.commands.dump")
    assert "no system message" in out.lower()


# ---- /hooks ---------------------------------------------------------


def test_hooks_no_hooks_message() -> None:
    """No hooks configured -> the slash command surfaces a "no hooks"
    message that mentions settings.json so the user knows where to
    drop one. Plugin-driven path post-R5."""
    from athena.commands.hooks import cmd_hooks

    fake_plugin = SimpleNamespace(name="shell_hook", _hooks=[])
    agent = SimpleNamespace(plugin_hooks=SimpleNamespace(plugins=[fake_plugin]))
    out = _run(cmd_hooks, agent, "", "athena.commands.hooks")
    assert "no hooks" in out.lower()
    assert "settings.json" in out


def test_hooks_lists_configured_hooks() -> None:
    """``/hooks`` reads from the bundled ShellHookPlugin's ``_hooks`` list.
    Phase 18.1 R5 retired the legacy ``athena.hooks.list_hooks`` path; the
    slash handler now looks at the plugin's internal hook list directly."""
    from athena.commands.hooks import cmd_hooks

    fake_hooks = [
        SimpleNamespace(event="PostToolUse", matcher="Bash", command="echo done"),
        SimpleNamespace(event="UserPromptSubmit", matcher=".*", command="logger -t athena"),
    ]
    fake_plugin = SimpleNamespace(name="shell_hook", _hooks=fake_hooks)
    agent = SimpleNamespace(plugin_hooks=SimpleNamespace(plugins=[fake_plugin]))
    out = _run(cmd_hooks, agent, "", "athena.commands.hooks")
    assert "PostToolUse" in out
    assert "Bash" in out
    assert "echo done" in out
    assert "UserPromptSubmit" in out
    assert "logger -t athena" in out


# ---- /tools ---------------------------------------------------------


def test_tools_lists_with_name_and_first_line_of_description() -> None:
    from athena.commands import tools as tools_cmd

    fake_tools = [
        SimpleNamespace(
            name="Read",
            description="Reads a file from disk.\nMore detail here.",
            requires_confirmation=False,
        ),
        SimpleNamespace(
            name="Bash",
            description="Runs a shell command.",
            requires_confirmation=True,
        ),
        SimpleNamespace(
            name="server1__do_thing",  # MCP-style name
            description="MCP tool that does the thing.",
            requires_confirmation=False,
        ),
    ]
    agent = SimpleNamespace(cfg=SimpleNamespace(disabled_tools=[]))
    with patch(
        "athena.commands.tools.tools.all_tools",
        return_value=fake_tools,
    ):
        out = _run(tools_cmd.cmd_tools, agent, "", "athena.commands.tools")
    assert "Read" in out
    assert "Reads a file from disk." in out
    # "More detail here." should NOT appear — only first line of description.
    assert "More detail here." not in out
    # confirmation marker on Bash
    assert "Bash" in out
    assert "[confirm]" in out
    # MCP marker on namespaced tool name
    assert "[mcp]" in out


def test_tools_passes_disabled_tools_through_to_registry() -> None:
    """``/tools`` must honor the agent's disabled_tools so users see
    the same surface the model sees."""
    from athena.commands import tools as tools_cmd

    agent = SimpleNamespace(cfg=SimpleNamespace(disabled_tools=["Bash", "Edit"]))
    captured_kwargs: dict = {}

    def _spy(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return []

    with patch("athena.commands.tools.tools.all_tools", side_effect=_spy):
        _run(tools_cmd.cmd_tools, agent, "", "athena.commands.tools")
    assert captured_kwargs.get("disabled") == ["Bash", "Edit"]


# ---- /models --------------------------------------------------------


def test_models_lists_with_active_marker() -> None:
    from athena.commands.models import cmd_models

    agent = SimpleNamespace(
        model="qwen2.5-coder:14b",
        provider=SimpleNamespace(
            list_models=lambda: ["llama3.2:3b", "qwen2.5-coder:14b", "gemma:7b"],
        ),
    )
    out = _run(cmd_models, agent, "", "athena.commands.models")
    assert "llama3.2:3b" in out
    assert "qwen2.5-coder:14b" in out
    assert "gemma:7b" in out
    # Active model line must have the * marker; inactive must not.
    active_line = next(l for l in out.splitlines() if "qwen2.5-coder:14b" in l)
    assert "*" in active_line
    inactive_line = next(l for l in out.splitlines() if "llama3.2:3b" in l)
    assert "*" not in inactive_line


def test_models_handles_provider_error() -> None:
    """Provider errors must not crash the REPL — surface a friendly
    ``ui.error`` instead."""
    from athena.commands.models import cmd_models

    def _raise():
        raise ConnectionError("Ollama not running on :11434")

    agent = SimpleNamespace(
        model="x",
        provider=SimpleNamespace(list_models=_raise),
    )
    out = _run(cmd_models, agent, "", "athena.commands.models")
    assert "could not list models" in out.lower()
    assert "ollama not running" in out.lower()


# ---- /cost ----------------------------------------------------------


def test_cost_prints_session_counters() -> None:
    from athena.commands.cost import cmd_cost

    # 60s ago started; some activity recorded.
    stats = SimpleNamespace(
        started=time.time() - 60.0,
        turns=3,
        tool_calls=11,
        prompt_tokens=1234,
        eval_tokens=5678,
    )
    agent = SimpleNamespace(stats=stats)
    out = _run(cmd_cost, agent, "", "athena.commands.cost")
    assert "turns" in out and "3" in out
    assert "tool calls" in out and "11" in out
    assert "1234" in out
    assert "5678" in out
    # Elapsed seconds rendered as a float; 60s ago should give ~60.0s
    assert "elapsed" in out
    # Pluck out the elapsed number — should be roughly 60.
    import re
    match = re.search(r"elapsed:\s*([\d.]+)s", out)
    assert match, f"no elapsed line in: {out!r}"
    elapsed = float(match.group(1))
    assert 59.0 < elapsed < 62.0


def test_cost_handles_zero_counters() -> None:
    """A fresh session (no turns yet) must still render without
    error rather than dividing by zero or formatting None."""
    from athena.commands.cost import cmd_cost

    agent = SimpleNamespace(
        stats=SimpleNamespace(
            started=time.time(),
            turns=0,
            tool_calls=0,
            prompt_tokens=0,
            eval_tokens=0,
        ),
    )
    out = _run(cmd_cost, agent, "", "athena.commands.cost")
    assert "0" in out
    assert "elapsed" in out
