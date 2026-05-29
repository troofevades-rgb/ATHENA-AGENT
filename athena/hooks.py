"""DEPRECATED -- settings.json hook system.

This module shipped in Phase 0 as athena's port of Claude Code's hook events
(``PreToolUse`` / ``PostToolUse`` / ``UserPromptSubmit`` / ``Stop``). It now
delegates entirely to the bundled :class:`ShellHookPlugin`
(``athena/plugins/bundled/shell_hook/plugin.py``); the agent loop reads
hooks via the plugin layer, not through this module.

This file remains as a backward-compatibility shim for one release so any
external code that imports ``athena.hooks.fire`` / ``athena.hooks.load_hooks``
keeps working with a deprecation warning. Internal callers have already
been migrated.

Deletion plan: drop this module the release after we cut next. The
shim emits a ``DeprecationWarning`` on import so any holdout caller surfaces.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

warnings.warn(
    "athena.hooks is deprecated; the settings.json hooks block is now read "
    "by athena/plugins/bundled/shell_hook/ (ShellHookPlugin). Internal "
    "callers have been migrated; external imports should switch to the "
    "plugin layer.",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass
class Hook:
    """Legacy hook record. Kept so external code that imports the dataclass
    type still resolves -- the plugin uses its own internal record type."""

    event: str
    matcher: str
    command: str


def load_hooks(workspace: Path) -> list[Hook]:
    """Compat shim: load hooks via the plugin and return them in the legacy
    :class:`Hook` shape.

    Internal callers no longer need this -- the bundled ``ShellHookPlugin``
    loads its own hook list on ``on_session_start`` and re-reads on
    ``configure_workspace``. This function is preserved so external scripts
    that called ``athena.hooks.load_hooks(workspace)`` keep working.
    """
    from .plugins.bundled.shell_hook.plugin import _load_hooks as _plugin_load

    raw = _plugin_load(workspace)
    return [Hook(event=h.event, matcher=h.matcher, command=h.command) for h in raw]


def list_hooks() -> list[Hook]:
    """Compat shim: returns an empty list. The legacy module kept a
    module-level ``_HOOKS`` populated by ``load_hooks``; the plugin owns
    its own list now. Slash command ``/hooks`` reads directly from the
    plugin (see ``athena/commands/hooks_cmd.py``).
    """
    return []


def fire(
    event: str, *, tool_name: str = "", payload: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Compat shim: dispatch through a fresh ShellHookPlugin run.

    External callers that fire events directly (rare) still get the correct
    side-effect behaviour, but at the cost of re-reading settings.json on
    every call. Internal callers have moved to the plugin layer where the
    settings load is cached.
    """
    from .plugins.bundled.shell_hook.plugin import (
        _load_hooks as _plugin_load,
        _run_shell_hooks as _plugin_run,
    )

    hooks = _plugin_load(None)
    blocking = event in ("PreToolUse", "UserPromptSubmit")
    return _plugin_run(
        hooks,
        event,
        tool_name=tool_name,
        payload=payload or {},
        blocking=blocking,
    )
