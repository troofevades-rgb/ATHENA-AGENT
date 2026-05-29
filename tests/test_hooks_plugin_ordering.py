"""Pin the firing order of plugin lifecycle hooks within ``_handle_tool_call``.

Before Refactor 5 (R5 in REFACTOR_PLAN.md), this file pinned a "settings
hooks fire BEFORE plugin hooks" contract because ``athena/hooks.py`` and
``athena/plugins/`` were two parallel hook systems both invoked from
``_handle_tool_call``. R5 retired ``athena/hooks.py`` and routed the
settings.json hooks block through ``ShellHookPlugin`` (a bundled plugin
enabled by default), so there's no separate "settings" path to order
against plugins anymore -- it's plugins all the way down.

The contract this file now pins:

  pre  →  dispatch  →  post

with veto semantics:
  * first plugin returning False from pre_tool_call blocks dispatch;
  * a plugin raising in either phase must not break the rest of the chain.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture
def call_log() -> list[str]:
    return []


@pytest.fixture
def fake_agent(call_log: list[str], tmp_path: Path):
    """Minimal Agent stub that exposes just what ``_handle_tool_call`` reads.

    Building a real Agent in a test is expensive (loads system prompt,
    plugins, session store). We bind the real ``_handle_tool_call`` method
    to a SimpleNamespace stub instead.
    """
    from athena.agent.core import Agent, Stats
    from athena.config import Config

    class _RecordingPluginDispatcher:
        def pre_tool_call(self, name: str, args: dict) -> tuple[bool, str | None]:
            call_log.append(f"plugin:pre:{name}")
            return True, None

        def post_tool_call(self, name: str, args: dict, result: Any) -> None:
            call_log.append(f"plugin:post:{name}")

    cfg = Config()
    cfg.disabled_tools = []
    cfg.bash_allowlist = []
    cfg.tool_call_sanitize = False

    stub = SimpleNamespace(
        cfg=cfg,
        stats=Stats(),
        plugin_hooks=_RecordingPluginDispatcher(),
        workspace=tmp_path,
        messages=[{"role": "system", "content": "sys"}],
        _record_tool_result=lambda call, name, result: call_log.append(
            f"record_result:{name}"
        ),
        _preview_write=lambda args: None,
        _maybe_store_tool_result=lambda name, result: result,
    )
    stub._handle_tool_call = Agent._handle_tool_call.__get__(stub)
    return stub


def _mk_call(tool_name: str = "Read", args: dict | None = None) -> dict:
    return {
        "id": "call_xyz",
        "function": {
            "name": tool_name,
            "arguments": args or {"file_path": "ATHENA.md"},
        },
    }


# ---- pre → dispatch → post --------------------------------------------------


def test_dispatch_runs_between_pre_and_post(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: pre_tool_call fires, then tools.dispatch runs, then
    post_tool_call fires. The plugin dispatcher is the single entry
    point for both phases."""
    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda name, args: (call_log.append(f"dispatch:{name}"), "result")[1],
    )
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    sequence = ["plugin:pre:Read", "dispatch:Read", "plugin:post:Read"]
    last_idx = -1
    for event in sequence:
        try:
            idx = call_log.index(event, last_idx + 1)
        except ValueError:
            pytest.fail(f"event {event!r} missing from call_log {call_log}")
        assert idx > last_idx, f"event {event!r} out of order"
        last_idx = idx


# ---- Veto semantics --------------------------------------------------------


def test_plugin_pre_veto_blocks_dispatch(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a plugin pre_tool_call returns ``False``, the tool must not
    dispatch. ShellHookPlugin bridges legacy settings.json PreToolUse
    hooks into this path, so the same veto semantics cover both."""
    class _BlockingPluginDispatcher:
        def pre_tool_call(self, name, args):
            call_log.append(f"plugin:pre:{name}")
            return False, "blocked by test"

        def post_tool_call(self, name, args, result):
            call_log.append(f"plugin:post:{name}")

    fake_agent.plugin_hooks = _BlockingPluginDispatcher()

    dispatched: list[str] = []
    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda n, a: (dispatched.append(n), "")[1],
    )
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.warn", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    assert "plugin:pre:Read" in call_log
    assert dispatched == [], (
        f"tool dispatched despite plugin veto: {dispatched!r}"
    )


# ---- Resilience ------------------------------------------------------------


def test_real_dispatcher_isolates_individual_plugin_failures(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single plugin that raises must not poison the rest of the chain
    or break the agent. Test by giving the REAL HookDispatcher a crashing
    plugin alongside a healthy one. Both must be invoked; dispatch must
    still run."""
    from athena.plugins.base import Plugin
    from athena.plugins.hooks import HookDispatcher

    class _CrashingPlugin(Plugin):
        name = "crasher"
        version = "0.0.0"

        def pre_tool_call(self, tool_name: str, tool_args: dict) -> bool | None:
            call_log.append("plugin:crasher:pre")
            raise RuntimeError("intentional test failure")

        def post_tool_call(self, tool_name, tool_args, result):
            call_log.append("plugin:crasher:post")
            raise RuntimeError("intentional test failure (post)")

    class _HealthyPlugin(Plugin):
        name = "healthy"
        version = "0.0.0"

        def pre_tool_call(self, tool_name, tool_args):
            call_log.append("plugin:healthy:pre")
            return None

        def post_tool_call(self, tool_name, tool_args, result):
            call_log.append("plugin:healthy:post")

    fake_agent.plugin_hooks = HookDispatcher(
        plugins=[_CrashingPlugin(), _HealthyPlugin()],
    )

    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda n, a: (call_log.append(f"dispatch:{n}"), "ok")[1],
    )
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.warn", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    assert "plugin:crasher:pre" in call_log
    assert "plugin:healthy:pre" in call_log
    assert "dispatch:Read" in call_log
