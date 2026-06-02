"""Agent.fork() — the daemon-thread sub-agent primitive.

A fork is a fresh ``Agent`` instance run on a daemon thread with:

- a scoped tool set (``enabled_toolsets``) plus optional per-name disables,
- an injected ``system_addendum`` describing what the fork should do,
- a write-origin ContextVar bound for the duration of the work,
- the ``AUTO_DENY`` approval callback so confirmation prompts can't deadlock,
- an isolated provider client (so the parent's connection pool / KV cache
  is undisturbed), and
- a child session in the parent's ``SessionStore`` with ``parent_session_id``
  set, so ``athena sessions browse`` shows the fork tree.

Stdout and stderr captured by the fork's thread are surfaced via
:class:`ForkResult` so callers can inspect them after the join.

Two signature additions vs. the design doc:

- ``user_prompt: str = ""`` lets sub-agent dispatch pass the user's brief as
  a normal user message without synthesizing an empty turn.
- ``disabled_tools: list[str] | None = None`` lets callers subtract specific
  tool names within the chosen toolsets (the Explore / Plan sub-agents need
  this — the ``"file"`` toolset includes Write / Edit).
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..provenance import BACKGROUND_REVIEW
from .auxiliary_client import build_auxiliary_client

if TYPE_CHECKING:
    from .core import Agent

logger = logging.getLogger(__name__)


@dataclass
class ForkAction:
    """A structured action record extracted from a tool result.

    Tools that return ``{"success": true, "target": ..., "action": ...}`` JSON
    (notably ``skill_manage``) produce one of these per call. The parent agent
    uses ``ForkResult.actions`` to summarize what a background review or
    curator fork did without re-reading every tool message.
    """

    action: str  # "created" | "updated" | "deleted" | "patched" | "pin" | ...
    target: str  # "skill" | "memory" | "file"
    name: str
    detail: str | None = None


@dataclass
class ForkResult:
    final_response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    actions: list[ForkAction] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    duration_s: float = 0.0
    child_session_id: str | None = None


def fork(
    self: Agent,
    *,
    enabled_toolsets: list[str],
    system_addendum: str,
    user_prompt: str = "",
    conversation_history: list[dict] | None = None,
    max_iterations: int = 16,
    write_origin: str = BACKGROUND_REVIEW,
    auxiliary_client: bool = True,
    quiet: bool = True,
    disabled_tools: list[str] | None = None,
) -> ForkResult:
    """Spawn a forked Agent on a daemon thread."""
    start = time.monotonic()

    # 1. Build child Config inheriting from parent. cfg.profile is preserved
    #    so the child session lands under the same profile root as the
    #    parent — we share the parent's SessionStore object below.
    child_cfg = dataclasses.replace(
        self.cfg,
        enabled_toolsets=list(enabled_toolsets),
        disabled_tools=list(disabled_tools)
        if disabled_tools is not None
        else list(self.cfg.disabled_tools),
        auto_approve_tools=True,
        lean_prompt=True,
        max_turn_steps=max_iterations,
    )

    # 2. Construct child agent — defer import so module load order is safe.
    from .core import Agent, _current_agent

    client = build_auxiliary_client(self) if auxiliary_client else self.client
    # Inherit the parent's plugin dispatcher so policy plugins
    # (shell_audit, allowlists, custom vetoes) apply inside forks
    # too. Without this the child Agent falls through to an empty
    # HookDispatcher and any pre_tool_call veto wired in by a
    # plugin is silently ignored inside background_review and
    # curator forks -- a real escape hatch for a plugin that, e.g.,
    # blocks Bash in the REPL.
    # Construct the child agent under a UI mute when quiet. Agent
    # __init__ runs _build_system() which emits startup chatter
    # ("inherited SYSTEM", "loaded ATHENA.md", "loaded skills
    # catalog") via ui.info — and construction happens HERE on the
    # calling thread, BEFORE the stdout-redirect set up inside the
    # fork's _runner thread. Without the mute those messages leak to
    # the console, showing as a duplicate boot banner whenever a fork
    # fires before the TUI gateway is wired (notably the curator's
    # session-start pass). The mute is thread-local, so it never
    # suppresses the parent/main thread's concurrent output.
    from .. import ui

    with ui.muted() if quiet else contextlib.nullcontext():
        child = Agent(
            child_cfg,
            self.workspace,
            model=self.model,
            client=client,
            session_store=self.session_store,
            parent_session_id=self.session_id,
            plugin_hooks=self.plugin_hooks,
        )
    # If we built an auxiliary client, the child owns it (close on shutdown).
    # If we passed the parent's client, the child does NOT own it.
    child._owns_client = auxiliary_client

    result = ForkResult(final_response="", child_session_id=child.session_id)

    try:
        # 3. Pin the child's system prompt to the parent's verbatim, then
        #    append the addendum. The byte-exact prefix-cache key (Anthropic,
        #    OpenRouter) only stays warm if the prefix matches the parent's
        #    last warmed request — rebuilding the child's system prompt from
        #    scratch produces a different `today` date, a different skills
        #    catalog (the child has narrower toolsets), and a fresh
        #    Modelfile-SYSTEM fetch. Each divergence ends the cacheable
        #    prefix at that byte. Hermes Agent measured ~26% end-to-end cost
        #    reduction on Sonnet 4.5 by pinning the parent's prompt verbatim
        #    on review forks (issue #25322, PR #17276) — the same logic
        #    applies to every fork we spawn against a hosted provider.
        parent_system = (
            self.messages[0]["content"]
            if self.messages and self.messages[0].get("role") == "system"
            else child.messages[0]["content"]
        )
        if system_addendum:
            child.messages[0]["content"] = parent_system.rstrip() + "\n\n" + system_addendum
        else:
            child.messages[0]["content"] = parent_system

        # 4. Replace history if provided.
        if conversation_history is not None:
            child.messages = [child.messages[0], *conversation_history]

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        def _runner() -> None:
            from ..safety.path_security import set_workspace as set_ps_workspace
            from ..safety.thread_entry import non_foreground_thread
            from ..tools.clarify import in_fork_context

            # ContextVars don't propagate across thread boundaries, so the
            # fork sees the default path_security workspace (cwd) unless
            # we re-pin it. Inherit the parent's workspace explicitly.
            set_ps_workspace(child.workspace)
            # T2-08: tell the clarify tool we're inside a fork so it
            # AUTO_DENYs instead of blocking on stdin (which the fork
            # doesn't own anyway).
            in_fork_context.set(True)

            # write-origin + AUTO_DENY + fresh approval scope, all the
            # standard non-foreground thread-entry guards. The fork's own
            # bits (current-agent, quiet stdout/stderr capture) layer on
            # top.
            with non_foreground_thread(origin=write_origin):
                agent_token = _current_agent.set(child)
                try:
                    cm = contextlib.ExitStack()
                    if quiet:
                        cm.enter_context(contextlib.redirect_stdout(stdout_buf))
                        cm.enter_context(contextlib.redirect_stderr(stderr_buf))
                    with cm:
                        child.run_until_done(user_prompt, max_iterations=max_iterations)
                except Exception as exc:
                    logger.exception("fork failed")
                    result.error = f"{type(exc).__name__}: {exc}"
                finally:
                    _current_agent.reset(agent_token)

        t = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"athena-fork-{(child.session_id or 'anon')[:8]}",
        )
        t.start()
        t.join()

        # 5. Gather results from child state.
        result.final_response = child.last_assistant_message()
        result.tool_calls = child.tool_call_trace()
        result.actions = _extract_actions(child.messages)
        result.stdout = stdout_buf.getvalue()
        result.stderr = stderr_buf.getvalue()
        return result
    finally:
        try:
            child.close()
        except Exception:
            pass
        result.duration_s = time.monotonic() - start


def _extract_actions(messages: list[dict[str, Any]]) -> list[ForkAction]:
    """Walk tool result messages, extract structured ``ForkAction`` records.

    Tools that opt into the shape ``{"success": bool, "target": ...,
    "action": ..., "skill_name"|"memory_name"|"path": ...}`` yield one record
    per successful call. Free-form text tool results are skipped silently
    rather than failing — only structured results are summarizable.
    """
    actions: list[ForkAction] = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        if not isinstance(content, str) or not content.startswith("{"):
            continue
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        if not parsed.get("success"):
            continue
        if "action" not in parsed:
            continue
        actions.append(
            ForkAction(
                action=str(parsed.get("action") or ""),
                target=str(parsed.get("target") or "unknown"),
                name=str(
                    parsed.get("skill_name")
                    or parsed.get("memory_name")
                    or parsed.get("path")
                    or ""
                ),
                detail=parsed.get("message"),
            )
        )
    return actions
