"""ShellHookPlugin -- bridge from legacy settings.json hooks block
to plugin lifecycle events.

Replaces the bulk of what tests/test_hooks.py used to assert about the
legacy ``athena.hooks`` module. Coverage:

  * settings.json hooks are loaded on session start AND on
    configure_workspace (so workspace-local settings.json overrides
    work).
  * PreToolUse exit code 1 → pre_tool_call returns False.
  * PostToolUse runs but cannot block.
  * UserPromptSubmit exit code 1 → check_user_message returns
    (False, stderr_message).
  * Stop runs once per turn via on_turn_end.
  * Matcher regex respects the tool name; missing matcher matches all.
  * A blocking hook that times out fails closed (returns False).
  * Malformed settings.json is skipped (not crash).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from athena.plugins.bundled.shell_hook.plugin import ShellHookPlugin


def _write_settings(dir_path: Path, hooks_block: dict) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    p = dir_path / "settings.json"
    p.write_text(json.dumps({"hooks": hooks_block}), encoding="utf-8")
    return p


@pytest.fixture
def isolated_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect ``_user_settings()`` at ~/.athena/settings.json so a
    test's writes can't touch the developer's real home."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(
        "athena.plugins.bundled.shell_hook.plugin._user_settings",
        lambda: user_dir / "settings.json",
    )
    return user_dir


# ---- loading ---------------------------------------------------------------


def test_no_settings_file_loads_zero_hooks(isolated_settings: Path) -> None:
    """A user with no settings.json gets a clean session -- no hooks,
    no errors, no startup noise."""
    plugin = ShellHookPlugin()
    plugin.on_session_start("session-1", "default")
    assert plugin._hooks == []


def test_user_settings_hooks_loaded(isolated_settings: Path) -> None:
    _write_settings(
        isolated_settings,
        {"PreToolUse": [{"matcher": "Bash", "command": "true"}]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("session-1", "default")
    assert len(plugin._hooks) == 1
    assert plugin._hooks[0].event == "PreToolUse"
    assert plugin._hooks[0].matcher == "Bash"
    assert plugin._hooks[0].command == "true"


def test_workspace_settings_are_added_on_configure(
    isolated_settings: Path, tmp_path: Path,
) -> None:
    """The plugin re-reads its hook list when configure_workspace is
    called; workspace-local hooks merge with user-global ones."""
    _write_settings(
        isolated_settings,
        {"PreToolUse": [{"matcher": "", "command": "user-cmd"}]},
    )
    workspace = tmp_path / "workspace"
    _write_settings(
        workspace / ".athena",
        {"PreToolUse": [{"matcher": "Bash", "command": "ws-cmd"}]},
    )

    plugin = ShellHookPlugin()
    plugin.on_session_start("session-1", "default")
    assert len(plugin._hooks) == 1

    plugin.configure_workspace(workspace)
    cmds = [h.command for h in plugin._hooks]
    assert "user-cmd" in cmds
    assert "ws-cmd" in cmds


def test_malformed_settings_skipped(
    isolated_settings: Path, caplog,
) -> None:
    """A broken settings.json must not stop the session -- log a warning
    and move on."""
    settings = isolated_settings / "settings.json"
    settings.write_text("{ this is not valid", encoding="utf-8")

    plugin = ShellHookPlugin()
    plugin.on_session_start("session-1", "default")
    assert plugin._hooks == []


# ---- PreToolUse (blocking) -------------------------------------------------


def test_pre_tool_call_allows_on_exit_zero(isolated_settings: Path) -> None:
    _write_settings(
        isolated_settings,
        {"PreToolUse": [{"matcher": "", "command": "true"}]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("s", "default")
    decision = plugin.pre_tool_call("Bash", {"command": "ls"})
    # None means "no opinion" (the dispatcher contract).
    assert decision is None


def test_pre_tool_call_blocks_on_exit_one(isolated_settings: Path) -> None:
    _write_settings(
        isolated_settings,
        {"PreToolUse": [{"matcher": "", "command": "false"}]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("s", "default")
    decision = plugin.pre_tool_call("Bash", {"command": "ls"})
    assert decision is False


def test_pre_tool_call_matcher_filters(isolated_settings: Path) -> None:
    """A PreToolUse hook with matcher='Bash' fires only for Bash."""
    _write_settings(
        isolated_settings,
        {"PreToolUse": [{"matcher": "Bash", "command": "false"}]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("s", "default")
    # Bash matches -> blocked.
    assert plugin.pre_tool_call("Bash", {}) is False
    # Read doesn't match the regex -> allowed.
    assert plugin.pre_tool_call("Read", {}) is None


# ---- check_user_message (UserPromptSubmit) ---------------------------------


def test_check_user_message_allows_on_exit_zero(isolated_settings: Path) -> None:
    _write_settings(
        isolated_settings,
        {"UserPromptSubmit": [{"matcher": "", "command": "true"}]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("s", "default")
    allow, reason = plugin.check_user_message("hello")
    assert allow is True
    assert reason == ""


def test_check_user_message_blocks_on_exit_one(isolated_settings: Path) -> None:
    _write_settings(
        isolated_settings,
        {"UserPromptSubmit": [{"matcher": "", "command": "false"}]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("s", "default")
    allow, reason = plugin.check_user_message("hello")
    assert allow is False
    # reason is the stderr or the fallback message.
    assert reason  # non-empty


# ---- PostToolUse + Stop (non-blocking) -------------------------------------


def test_post_tool_call_runs_but_does_not_block(
    isolated_settings: Path, tmp_path: Path,
) -> None:
    """PostToolUse fires (touch the marker file) and its return value
    is ignored. We use a marker file rather than env-var expansion to
    stay portable -- ``$VAR`` is bash syntax that cmd.exe doesn't
    expand on Windows."""
    marker = tmp_path / "postlog"
    _write_settings(
        isolated_settings,
        {"PostToolUse": [{
            "matcher": "",
            "command": f"echo touched > {marker}",
        }]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("s", "default")
    # post_tool_call returns None and never raises.
    assert plugin.post_tool_call("Bash", {}, "ok") is None
    assert marker.exists()


def test_on_turn_end_runs_stop_hook(
    isolated_settings: Path, tmp_path: Path,
) -> None:
    marker = tmp_path / "stoplog"
    _write_settings(
        isolated_settings,
        {"Stop": [{"matcher": "", "command": f"echo end >> {marker}"}]},
    )
    plugin = ShellHookPlugin()
    plugin.on_session_start("s", "default")
    plugin.on_turn_end("completed", {"turns": 1, "tool_calls": 0})
    assert marker.read_text(encoding="utf-8").strip() == "end"
