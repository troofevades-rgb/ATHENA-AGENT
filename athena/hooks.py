"""Hook system. Mirrors Claude Code's hook events.

Configuration in ~/.athena/settings.json or <workspace>/.athena/settings.json:

    {
      "hooks": {
        "PreToolUse": [
          {
            "matcher": "Bash",
            "command": "echo \"$tool_name $tool_args\" >> ~/.athena/audit.log"
          }
        ],
        "PostToolUse": [...],
        "UserPromptSubmit": [...],
        "Stop": [...]
      }
    }

Events:
  PreToolUse        — runs before each tool call. Receives JSON on stdin:
                      {"event": "PreToolUse", "tool_name": str, "tool_args": dict}
                      Exit code 1 BLOCKS the tool call (the command's stderr is
                      surfaced back to the model as the tool result).
  PostToolUse       — runs after each tool call. Receives:
                      {"event": "PostToolUse", "tool_name": str, "tool_args": dict, "result": str}
                      Cannot block; output is logged but ignored.
  UserPromptSubmit  — runs before each user prompt is sent to the model.
                      Receives: {"event": "UserPromptSubmit", "prompt": str}
                      Exit code 1 cancels the turn.
  Stop              — runs at end of turn (after the model returns no tool calls).
                      Receives: {"event": "Stop", "stats": {...}}

`matcher` is a regex matched against tool_name (substring fallback if the
regex fails to compile). Empty/missing matcher matches all tools.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ui
from .config import CONFIG_DIR

SETTINGS_NAME = "settings.json"
USER_SETTINGS = CONFIG_DIR / SETTINGS_NAME


@dataclass
class Hook:
    event: str
    matcher: str  # substring match against tool_name; "" = match all
    command: str


_HOOKS: list[Hook] = []


def settings_paths(workspace: Path) -> list[Path]:
    """User-level then workspace-level. Later overrides earlier per-event,
    but we just concatenate hook lists in order so all configured hooks fire.
    """
    return [
        USER_SETTINGS,
        workspace / ".athena" / SETTINGS_NAME,
    ]


def load_hooks(workspace: Path) -> list[Hook]:
    """Read settings files, build the hook list. Resets module state."""
    global _HOOKS
    _HOOKS = []
    for p in settings_paths(workspace):
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            ui.error(f"failed to parse {p}: {e}")
            continue
        hooks_block = data.get("hooks") or {}
        if not isinstance(hooks_block, dict):
            ui.error(f"{p}: 'hooks' must be an object")
            continue
        for event, entries in hooks_block.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                cmd = entry.get("command")
                if not isinstance(cmd, str) or not cmd.strip():
                    if cmd is not None:
                        ui.error(
                            f"{p}: hook command must be a non-empty string, got {type(cmd).__name__}"
                        )
                    continue
                _HOOKS.append(
                    Hook(
                        event=event,
                        matcher=entry.get("matcher", "") or "",
                        command=cmd,
                    )
                )
    if _HOOKS:
        ui.info(f"loaded {len(_HOOKS)} hook(s)")
    return _HOOKS


def _matches(hook: Hook, tool_name: str) -> bool:
    if not hook.matcher:
        return True
    # Treat as regex; fall back to substring on regex error.
    try:
        return re.search(hook.matcher, tool_name) is not None
    except re.error:
        return hook.matcher in tool_name


def fire(
    event: str, *, tool_name: str = "", payload: dict[str, Any] | None = None
) -> tuple[bool, str]:
    """Fire all hooks matching this event.

    Returns (allow, message). For PreToolUse / UserPromptSubmit, allow=False
    blocks the action and message contains the reason (the hook's stderr).
    For other events, allow is always True.
    """
    payload = payload or {}
    payload["event"] = event
    payload_json = json.dumps(payload, default=str)
    blocking = event in ("PreToolUse", "UserPromptSubmit")
    for hook in _HOOKS:
        if hook.event != event:
            continue
        if not _matches(hook, tool_name):
            continue
        try:
            proc = subprocess.run(
                hook.command,
                shell=True,
                input=payload_json,
                capture_output=True,
                text=True,
                timeout=30,
                env={
                    **os.environ,
                    "ATHENA_HOOK_EVENT": event,
                    "ATHENA_TOOL_NAME": tool_name,
                },
            )
        except subprocess.TimeoutExpired:
            ui.warn(f"hook {event} timed out: {hook.command!r}")
            if blocking:
                # Fail closed: a blocking hook that hangs must not be a bypass.
                return False, f"hook {event} timed out (treating as block)"
            continue
        if proc.stdout.strip():
            ui.info(f"hook {event} stdout: {proc.stdout.strip()[:200]}")
        if blocking and proc.returncode != 0:
            msg = proc.stderr.strip() or f"hook {event} blocked the action (exit {proc.returncode})"
            return False, msg
    return True, ""


def list_hooks() -> list[Hook]:
    return list(_HOOKS)
