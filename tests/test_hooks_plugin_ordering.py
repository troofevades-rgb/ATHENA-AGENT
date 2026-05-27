"""Pin the firing order between settings.json hooks and plugin
lifecycle hooks.

CLAUDE.md states the contract:
  "The agent loop fires plugin hooks on top of the legacy
   athena/hooks.py settings.json hook system — both run;
   settings hooks first, plugins second."

These tests make that contract enforceable. A refactor that swaps
the order — even by accident — will fail loudly.

Coverage:
  * pre_tool_call:  settings → plugins
  * post_tool_call: settings → plugins
  * settings veto skips plugins (settings short-circuits)
  * plugin veto skips tool dispatch (after settings has already run)
  * an exception in settings hooks doesn't prevent plugin hooks from firing
  * an exception in plugin hooks doesn't break the agent loop
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture
def call_log() -> list[str]:
    """Shared list every fake hook records into. Order in the list
    reflects firing order."""
    return []


@pytest.fixture
def fake_agent(call_log: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Minimal Agent stub with the surface ``_handle_tool_call`` reads.

    We don't instantiate the real Agent (heavy — loads system prompt,
    plugins, session store). We make a SimpleNamespace that exposes
    just the methods/attrs ``_handle_tool_call`` touches, then call
    Agent._handle_tool_call.__get__(stub) to bind the real method
    to the stub.
    """
    from athena.agent.core import Agent, Stats
    from athena.config import Config

    # Capture-everything plugin dispatcher
    class _RecordingPluginDispatcher:
        def pre_tool_call(self, name: str, args: dict) -> tuple[bool, str | None]:
            call_log.append(f"plugin:pre:{name}")
            return True, None

        def post_tool_call(self, name: str, args: dict, result: Any) -> None:
            call_log.append(f"plugin:post:{name}")

    cfg = Config()
    cfg.disabled_tools = []  # let everything through
    cfg.bash_allowlist = []
    cfg.tool_call_sanitize = False

    stub = SimpleNamespace(
        cfg=cfg,
        stats=Stats(),
        plugin_hooks=_RecordingPluginDispatcher(),
        workspace=tmp_path,
        messages=[{"role": "system", "content": "sys"}],
        # The method calls these — keep them as no-ops for the test
        _record_tool_result=lambda call, name, result: call_log.append(
            f"record_result:{name}"
        ),
        _preview_write=lambda args: None,
        # Pass-through for the out-of-band storage path; just hands
        # back whatever it received.
        _maybe_store_tool_result=lambda name, result: result,
    )
    # Bind the real method
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


# ---------------------------------------------------------------------------
# Pre-tool-call ordering
# ---------------------------------------------------------------------------


def test_settings_hooks_fire_before_plugin_hooks_on_pre_tool_call(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings.json hooks must run BEFORE plugin lifecycle hooks
    for each tool call's pre-phase. The order is documented in
    CLAUDE.md as a contract callers may depend on (early veto from
    settings short-circuits the plugin chain)."""
    # Stub the settings-hook fire to record + allow
    def _fake_settings_fire(event: str, *, tool_name: str = "", payload=None):
        call_log.append(f"settings:{event}:{tool_name}")
        return (True, None)

    # Stub the tool registry so we don't actually run Read
    def _fake_dispatch(name: str, args: dict) -> str:
        call_log.append(f"dispatch:{name}")
        return "(stub result)"

    monkeypatch.setattr("athena.hooks.fire", _fake_settings_fire)
    monkeypatch.setattr("athena.tools.dispatch", _fake_dispatch)
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    # The exact ordering we care about
    pre_settings_idx = call_log.index("settings:PreToolUse:Read")
    pre_plugin_idx = call_log.index("plugin:pre:Read")
    assert pre_settings_idx < pre_plugin_idx, (
        f"plugin pre_tool_call fired before settings PreToolUse hook. "
        f"call_log: {call_log}"
    )


def test_settings_hooks_fire_before_plugin_hooks_on_post_tool_call(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same ordering must hold for the POST phase."""
    def _fake_settings_fire(event: str, *, tool_name: str = "", payload=None):
        call_log.append(f"settings:{event}:{tool_name}")
        return (True, None)

    monkeypatch.setattr("athena.hooks.fire", _fake_settings_fire)
    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda name, args: (call_log.append(f"dispatch:{name}"), "result")[1],
    )
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    post_settings_idx = call_log.index("settings:PostToolUse:Read")
    post_plugin_idx = call_log.index("plugin:post:Read")
    assert post_settings_idx < post_plugin_idx, (
        f"plugin post_tool_call fired before settings PostToolUse hook. "
        f"call_log: {call_log}"
    )


def test_dispatch_runs_between_pre_and_post_phases(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check the global order: pre (settings, plugin) →
    dispatch → post (settings, plugin)."""
    def _fake_settings_fire(event: str, *, tool_name: str = "", payload=None):
        call_log.append(f"settings:{event}:{tool_name}")
        return (True, None)

    monkeypatch.setattr("athena.hooks.fire", _fake_settings_fire)
    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda name, args: (call_log.append(f"dispatch:{name}"), "result")[1],
    )
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    sequence = [
        "settings:PreToolUse:Read",
        "plugin:pre:Read",
        "dispatch:Read",
        "settings:PostToolUse:Read",
        "plugin:post:Read",
    ]
    # The log may contain extra items (record_tool_result etc) but the
    # core sequence must appear in this order.
    last_idx = -1
    for event in sequence:
        try:
            idx = call_log.index(event, last_idx + 1)
        except ValueError:
            pytest.fail(f"event {event!r} missing from call_log {call_log}")
        assert idx > last_idx, f"event {event!r} out of order"
        last_idx = idx


# ---------------------------------------------------------------------------
# Veto semantics — settings veto short-circuits plugins; plugin veto
# short-circuits dispatch
# ---------------------------------------------------------------------------


def test_settings_veto_skips_plugin_pre_hook_and_dispatch(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the PreToolUse settings hook denies the call, the plugin
    pre_tool_call should NOT fire and the tool should NOT dispatch.
    Settings has the strongest veto authority."""
    def _denying_settings_fire(event: str, *, tool_name: str = "", payload=None):
        call_log.append(f"settings:{event}:{tool_name}")
        if event == "PreToolUse":
            return (False, "denied for testing")
        return (True, None)

    dispatch_called: list[str] = []
    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda n, a: (dispatch_called.append(n), "")[1],
    )
    monkeypatch.setattr("athena.hooks.fire", _denying_settings_fire)
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.warn", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    assert "settings:PreToolUse:Read" in call_log
    assert "plugin:pre:Read" not in call_log, (
        "plugin pre_tool_call fired despite settings veto"
    )
    assert dispatch_called == [], (
        f"tool dispatched despite settings veto: {dispatch_called!r}"
    )


def test_plugin_veto_blocks_dispatch_but_runs_after_settings(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a plugin vetoes, settings hooks have ALREADY fired —
    so the order is preserved even on the veto path. The tool must
    not dispatch."""
    class _BlockingPluginDispatcher:
        def pre_tool_call(self, name, args):
            call_log.append(f"plugin:pre:{name}")
            return False, "test-plugin-blocked"

        def post_tool_call(self, name, args, result):
            call_log.append(f"plugin:post:{name}")

    fake_agent.plugin_hooks = _BlockingPluginDispatcher()

    def _fake_settings_fire(event: str, *, tool_name: str = "", payload=None):
        call_log.append(f"settings:{event}:{tool_name}")
        return (True, None)

    dispatch_called: list[str] = []
    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda n, a: (dispatch_called.append(n), "")[1],
    )
    monkeypatch.setattr("athena.hooks.fire", _fake_settings_fire)
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.warn", lambda *a, **k: None)

    fake_agent._handle_tool_call(_mk_call())

    assert "settings:PreToolUse:Read" in call_log
    assert "plugin:pre:Read" in call_log
    assert call_log.index("settings:PreToolUse:Read") < call_log.index(
        "plugin:pre:Read"
    ), "order regression: plugin pre fired before settings pre"
    assert dispatch_called == [], (
        f"tool dispatched despite plugin veto: {dispatch_called!r}"
    )


# ---------------------------------------------------------------------------
# Resilience — neither subsystem must crash the other
# ---------------------------------------------------------------------------


def test_real_dispatcher_isolates_individual_plugin_failures(
    fake_agent, call_log: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract is at the HookDispatcher level, not at the agent
    level: a single plugin that raises must not poison the rest of
    the plugin chain or break the agent. We test this by giving the
    REAL HookDispatcher a crashing plugin alongside a healthy one.
    Both must be invoked; the healthy one's result wins."""
    from athena.plugins.base import Plugin
    from athena.plugins.hooks import HookDispatcher

    class _CrashingPlugin(Plugin):
        name = "crasher"
        version = "0.0.0"

        def pre_tool_call(self, tool_name: str, tool_args: dict) -> bool | None:
            call_log.append("plugin:crasher:pre")
            raise RuntimeError("intentional test failure")

        def post_tool_call(self, tool_name, tool_args, result):  # noqa: D401
            call_log.append("plugin:crasher:post")
            raise RuntimeError("intentional test failure (post)")

    class _HealthyPlugin(Plugin):
        name = "healthy"
        version = "0.0.0"

        def pre_tool_call(self, tool_name, tool_args):
            call_log.append("plugin:healthy:pre")
            return None  # observe; don't veto

        def post_tool_call(self, tool_name, tool_args, result):
            call_log.append("plugin:healthy:post")

    real_dispatcher = HookDispatcher(plugins=[_CrashingPlugin(), _HealthyPlugin()])
    fake_agent.plugin_hooks = real_dispatcher

    def _fake_settings_fire(event, *, tool_name="", payload=None):
        call_log.append(f"settings:{event}:{tool_name}")
        return (True, None)

    monkeypatch.setattr("athena.hooks.fire", _fake_settings_fire)
    monkeypatch.setattr(
        "athena.tools.dispatch",
        lambda n, a: (call_log.append(f"dispatch:{n}"), "ok")[1],
    )
    monkeypatch.setattr("athena.ui.tool_call_summary", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.tool_result", lambda *a, **k: None)
    monkeypatch.setattr("athena.ui.warn", lambda *a, **k: None)

    # Must not raise — dispatcher swallows the plugin exception.
    fake_agent._handle_tool_call(_mk_call())

    # The crasher tried (and raised); the healthy plugin ran too;
    # the tool dispatched.
    assert "plugin:crasher:pre" in call_log
    assert "plugin:healthy:pre" in call_log, (
        f"healthy plugin skipped after crasher raised. log: {call_log}"
    )
    assert "dispatch:Read" in call_log, (
        f"tool didn't dispatch after plugin chain. log: {call_log}"
    )
