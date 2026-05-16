"""Centralized plugin hook dispatcher.

Calls each lifecycle hook across all loaded plugins. Every call is wrapped
in ``try/except Exception``; failures are logged at ``ERROR`` level with the
plugin name and the agent continues. A broken plugin must never break the
agent.

``on_user_message`` is a *chain* — each plugin sees the output of the prior
plugin. A plugin that returns ``None`` is a pass-through. Every other hook
is *fan-out* — every plugin sees the same input and their return values
don't feed each other.

``pre_tool_call`` is a *hard veto*: the first plugin to return ``False``
blocks the tool call, but every plugin still gets called for observability.
The dispatcher returns the blocking plugin's name so the agent can surface
which plugin denied the call.

This module deliberately doesn't import :mod:`ocode.hooks` — the
settings-driven hook system there is a separate, additive layer.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import Plugin

logger = logging.getLogger(__name__)


class HookDispatcher:
    def __init__(self, plugins: list[Plugin]):
        self.plugins = list(plugins)

    # ---- Session lifecycle ----

    def on_session_start(self, session_id: str, profile: str) -> None:
        for p in self.plugins:
            try:
                p.on_session_start(session_id, profile)
            except Exception:
                logger.exception(
                    "plugin %s on_session_start raised; continuing", p.name
                )

    def on_session_end(
        self, session_id: str, completed: bool, interrupted: bool
    ) -> None:
        for p in self.plugins:
            try:
                p.on_session_end(session_id, completed, interrupted)
            except Exception:
                logger.exception(
                    "plugin %s on_session_end raised; continuing", p.name
                )

    # ---- Tool dispatch ----

    def pre_tool_call(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Return ``(allow, blocking_plugin_name_or_None)``.

        The first plugin to return ``False`` wins the veto; every subsequent
        plugin still sees the call for observability but cannot override.
        """
        allow = True
        blocker: str | None = None
        for p in self.plugins:
            try:
                decision = p.pre_tool_call(tool_name, dict(tool_args))
            except Exception:
                logger.exception(
                    "plugin %s pre_tool_call raised; allowing", p.name
                )
                continue
            if decision is False and allow:
                allow = False
                blocker = p.name
        return allow, blocker

    def post_tool_call(
        self, tool_name: str, tool_args: dict[str, Any], result: str
    ) -> None:
        for p in self.plugins:
            try:
                p.post_tool_call(tool_name, dict(tool_args), result)
            except Exception:
                logger.exception(
                    "plugin %s post_tool_call raised; continuing", p.name
                )

    # ---- Messages ----

    def on_user_message(self, prompt: str) -> str:
        """Chain prompt through every plugin. Each ``None`` is a pass-through."""
        current = prompt
        for p in self.plugins:
            try:
                modified = p.on_user_message(current)
            except Exception:
                logger.exception(
                    "plugin %s on_user_message raised; keeping prior prompt", p.name
                )
                continue
            if modified is not None:
                current = modified
        return current

    def on_assistant_message(self, content: str) -> None:
        for p in self.plugins:
            try:
                p.on_assistant_message(content)
            except Exception:
                logger.exception(
                    "plugin %s on_assistant_message raised; continuing", p.name
                )
