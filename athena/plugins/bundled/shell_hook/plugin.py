"""Bundled plugin: bridge legacy ``settings.json`` hooks into the plugin layer.

Reads the same ``settings.json`` ``hooks`` block ``athena/hooks.py`` used to read
and runs the same shell commands on the equivalent plugin lifecycle events:

  ============ ====================== ====================================
  settings.json   Plugin method          Behaviour
  ============ ====================== ====================================
  PreToolUse      pre_tool_call          Exit code 1 blocks the tool call.
  PostToolUse     post_tool_call         Observation only.
  UserPromptSubmit check_user_message    Exit code 1 cancels the turn.
  Stop            on_turn_end            Observation only.
  ============ ====================== ====================================

This plugin owns the settings.json hooks block. ``athena/hooks.py``
(the deprecation shim from Phase 0) was removed in the 0.3.0 dogfood
sweep; external callers should import from this plugin directly or
let the plugin's lifecycle hooks fire automatically.

Settings are loaded once on ``on_session_start`` from
``~/.athena/settings.json`` AND ``<workspace>/.athena/settings.json``.
Both files contribute (workspace appended after user-global) so the matrix
matches the prior behaviour exactly.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from athena.plugins.base import Plugin

logger = logging.getLogger(__name__)

_SETTINGS_NAME = "settings.json"
_HOOK_TIMEOUT_S = 30


@dataclass(frozen=True)
class _ShellHook:
    event: str
    matcher: str  # regex (substring fallback); "" matches all tools
    command: str


def _user_settings() -> Path:
    """``~/.athena/settings.json`` -- module-level so tests can monkeypatch."""
    from athena.config import CONFIG_DIR

    return Path(CONFIG_DIR) / _SETTINGS_NAME


def _settings_paths(workspace: Path | None) -> list[Path]:
    paths = [_user_settings()]
    if workspace is not None:
        paths.append(workspace / ".athena" / _SETTINGS_NAME)
    return paths


def _load_hooks(workspace: Path | None) -> list[_ShellHook]:
    """Read every settings.json and assemble the flat hook list. Malformed
    blocks log + skip rather than break the session."""
    hooks: list[_ShellHook] = []
    for p in _settings_paths(workspace):
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("shell_hook: failed to parse %s: %s", p, e)
            continue
        block = data.get("hooks") or {}
        if not isinstance(block, dict):
            logger.warning("shell_hook: %s 'hooks' must be an object", p)
            continue
        for event, entries in block.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                cmd = entry.get("command")
                if not isinstance(cmd, str) or not cmd.strip():
                    continue
                matcher = entry.get("matcher")
                if not isinstance(matcher, str):
                    matcher = ""
                hooks.append(_ShellHook(event=event, matcher=matcher, command=cmd))
    return hooks


def _matches(hook: _ShellHook, tool_name: str) -> bool:
    if not hook.matcher:
        return True
    try:
        return re.search(hook.matcher, tool_name) is not None
    except re.error:
        return hook.matcher in tool_name


def _run_shell_hooks(
    hooks: list[_ShellHook],
    event: str,
    *,
    tool_name: str,
    payload: dict[str, Any],
    blocking: bool,
) -> tuple[bool, str]:
    """Run every hook for ``event`` whose matcher accepts ``tool_name``.

    For ``blocking=True`` events (PreToolUse / UserPromptSubmit), exit
    code 1 (or a timeout) returns ``(False, stderr_or_reason)``. For
    non-blocking events (PostToolUse / Stop), the return is always
    ``(True, "")`` -- stdout is logged at INFO, errors at WARNING.
    """
    if not hooks:
        return True, ""
    payload = {**payload, "event": event}
    payload_json = json.dumps(payload, default=str)
    env = {
        **os.environ,
        "ATHENA_HOOK_EVENT": event,
        "ATHENA_TOOL_NAME": tool_name,
    }
    for hook in hooks:
        if hook.event != event:
            continue
        if tool_name and not _matches(hook, tool_name):
            continue
        try:
            proc = subprocess.run(
                hook.command,
                shell=True,
                input=payload_json,
                capture_output=True,
                text=True,
                timeout=_HOOK_TIMEOUT_S,
                env=env,
            )
        except subprocess.TimeoutExpired:
            logger.warning("shell_hook: %s timed out: %r", event, hook.command)
            if blocking:
                # Fail closed: a blocking hook that hangs must NOT be a
                # bypass route. Mirrors the legacy module's behaviour.
                return False, f"hook {event} timed out (treating as block)"
            continue
        if proc.stdout.strip():
            logger.info("shell_hook: %s stdout: %s", event, proc.stdout.strip()[:200])
        if blocking and proc.returncode != 0:
            msg = proc.stderr.strip() or (
                f"hook {event} blocked the action (exit {proc.returncode})"
            )
            return False, msg
    return True, ""


class ShellHookPlugin(Plugin):
    """Bridge from settings.json hooks block to plugin lifecycle events."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._hooks: list[_ShellHook] = []
        self._workspace: Path | None = None

    def on_session_start(self, session_id: str, profile: str) -> None:
        # The agent installs CONFIG_DIR + workspace .athena/ during init;
        # by the time on_session_start fires both directories exist.
        # We don't have direct access to the workspace path here, so we
        # leave it to ``configure_workspace`` (called by Agent.__init__
        # before any tool dispatch). Sessions without configure_workspace
        # only see ~/.athena/settings.json -- still correct for the
        # 90% of users without a workspace-local settings file.
        self._hooks = _load_hooks(self._workspace)
        if self._hooks:
            logger.info("shell_hook: loaded %d hook(s)", len(self._hooks))

    def configure_workspace(self, workspace: Path) -> None:
        """Wire the workspace path so workspace-local settings.json
        contributes too. Called by ``Agent.__init__`` before any tool
        dispatches happen; the plugin re-reads its hook list after.

        This is the one Plugin-ABC extension this shim needs that's
        specific to the shell_hook plugin -- it's not on the base
        Plugin class because no other plugin needs the workspace path
        at the same precise lifecycle moment.
        """
        self._workspace = workspace
        self._hooks = _load_hooks(self._workspace)

    # ---- Tool dispatch ----

    def pre_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> bool | None:
        allow, _ = _run_shell_hooks(
            self._hooks,
            "PreToolUse",
            tool_name=tool_name,
            payload={"tool_name": tool_name, "tool_args": tool_args},
            blocking=True,
        )
        return False if not allow else None

    def post_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: str,
    ) -> None:
        _run_shell_hooks(
            self._hooks,
            "PostToolUse",
            tool_name=tool_name,
            payload={"tool_name": tool_name, "tool_args": tool_args, "result": result},
            blocking=False,
        )

    # ---- Message hooks ----

    def check_user_message(self, prompt: str) -> tuple[bool, str]:
        return _run_shell_hooks(
            self._hooks,
            "UserPromptSubmit",
            tool_name="",
            payload={"prompt": prompt},
            blocking=True,
        )

    # ---- Turn lifecycle ----

    def on_turn_end(self, reason: str, stats: dict[str, Any]) -> None:
        _run_shell_hooks(
            self._hooks,
            "Stop",
            tool_name="",
            payload={"reason": reason, "stats": stats},
            blocking=False,
        )
