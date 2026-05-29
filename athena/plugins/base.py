"""Plugin ABC and lifecycle hooks.

Subclass :class:`Plugin` and override only the hooks you need; every default
is a no-op. The loader sets ``name`` and ``version`` from the plugin's
``plugin.toml`` manifest at load time, so subclasses do not normally need to
declare them.

Hooks observe and may modify. The agent loop does not depend on any single
hook for correctness — a broken plugin must never break the agent. Errors
inside hook calls are caught by the :class:`HookDispatcher`, logged, and
swallowed; the loop proceeds as if the failing plugin returned the default.
"""

from __future__ import annotations

from abc import ABC
from typing import Any


class Plugin(ABC):
    """Base class for plugins. All hooks have default no-op implementations.

    Class attributes ``name`` and ``version`` get rebound from the manifest
    when the loader instantiates the plugin. ``config`` is the plugin-specific
    config dict passed in by the loader (``config["plugins"][<name>]``).
    """

    # Set by the loader at instantiation time from PluginManifest.
    name: str = ""
    version: str = ""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config: dict[str, Any] = config or {}

    # ---- Install / activation ----

    def on_install(self) -> None:
        """Called once, the first time this plugin is activated.

        Use for one-time setup like creating directories. Tracked by the
        loader via ``.athena/plugins_installed``; subsequent activations skip
        this call.
        """

    # ---- Session lifecycle ----

    def on_session_start(self, session_id: str, profile: str) -> None:
        """Called at the start of every session."""

    def on_session_end(self, session_id: str, completed: bool, interrupted: bool) -> None:
        """Called at the end of every session.

        ``completed`` is True if the session finished cleanly; ``interrupted``
        is True if it ended via Ctrl+C or another user interrupt.
        """

    # ---- Tool dispatch ----

    def pre_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> bool | None:
        """Return ``False`` to block the tool call.

        ``None`` or ``True`` allow it. First plugin to return ``False`` wins;
        later plugins still see the call for observability but cannot
        override the veto.
        """
        return None

    def post_tool_call(self, tool_name: str, tool_args: dict[str, Any], result: str) -> None:
        """Observe tool call results. Cannot affect control flow."""

    # ---- Message hooks ----

    def check_user_message(self, prompt: str) -> tuple[bool, str]:
        """Decide whether a user prompt should be processed.

        Return ``(False, reason)`` to cancel the turn before any modification
        runs; ``(True, "")`` to allow it. Default is allow-through.

        Distinct from :meth:`on_user_message`: cancellation is a boolean
        decision, modification is a string transform. Plugins that want both
        must implement both. Added so the legacy settings.json
        ``UserPromptSubmit`` hook (exit code 1 cancels) has a plugin-shaped
        equivalent.
        """
        return True, ""

    def on_user_message(self, prompt: str) -> str | None:
        """Return a modified prompt, or ``None`` to leave it unchanged.

        Multiple plugins chain: each sees the output of the prior plugin in
        the dispatch order. Plugins that don't want to modify return ``None``.
        """
        return None

    def on_assistant_message(self, content: str) -> None:
        """Observe assistant messages after they're delivered."""

    # ---- Turn lifecycle ----

    def on_turn_end(self, reason: str, stats: dict[str, Any]) -> None:
        """Observe the end of one model turn.

        Fires once per ``run_turn`` cycle after the last model response,
        regardless of how the turn ended. ``reason`` is one of
        ``"completed"``, ``"cancelled"``, ``"step_limit"``. ``stats`` is a
        snapshot dict with token + tool-call counters.

        Distinct from :meth:`on_session_end` which fires once per session
        on Agent.close, not per turn. Added so the legacy settings.json
        ``Stop`` hook has a plugin-shaped equivalent.
        """
