"""Agent.fork() — the foundational primitive for sub-agents, background review,
and the curator. Lives at the agent layer, not in tools/.

A fork is a fresh ``Agent`` instance run on a daemon thread with:

- a scoped tool set (``enabled_toolsets``),
- an injected ``system_addendum`` describing what the fork should do,
- a ``write_origin`` ContextVar bound for the duration of the fork's work,
- the ``AUTO_DENY`` approval callback so the fork cannot deadlock on a
  confirmation prompt it has no way to satisfy.

The signature additions vs. the Phase 0 design doc (``user_prompt`` and
``disabled_tools``) are deliberate. ``user_prompt`` lets the sub-agent dispatch
tool keep its existing semantics — the user's brief flows in as a user message
without a synthetic empty turn. ``disabled_tools`` is a per-call override of the
inherited config so callers (notably the ``Agent`` tool's read-only Explore /
Plan scopes) can subtract specific tool names from the chosen toolsets without
pre-mutating the parent's config.
"""
from __future__ import annotations

import contextlib
import dataclasses
import os
import threading
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..provenance import (
    reset_current_write_origin,
    set_current_write_origin,
)
from ..safety.approval_callback import (
    AUTO_DENY,
    reset_approval_callback,
    set_approval_callback,
)

if TYPE_CHECKING:
    from .core import Agent


@dataclass
class ForkResult:
    """Outcome of a fork. ``final_response`` is the last assistant message text;
    ``tool_calls`` is the flat list of every tool call the fork made;
    ``actions`` is reserved for a future, higher-level summary of side effects
    (e.g. files created / updated) and is left empty in Phase 0; ``error`` is
    populated if the fork raised before producing a final response.
    """
    final_response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    error: str | None = None


def _devnull():
    """A file object that swallows writes, suitable for redirect_stdout."""
    # os.devnull is a path string ('nul' on Windows, '/dev/null' on POSIX).
    return open(os.devnull, "w", encoding="utf-8")


def fork(
    self: "Agent",
    *,
    enabled_toolsets: list[str],
    system_addendum: str,
    user_prompt: str = "",
    conversation_history: list[dict] | None = None,
    max_iterations: int = 16,
    write_origin: str = "background_review",
    auxiliary_client: bool = True,
    quiet: bool = True,
    disabled_tools: list[str] | None = None,
) -> ForkResult:
    """Spawn a forked Agent on a daemon thread. See module docstring."""
    # 1. Build child Config inheriting from parent.
    child_cfg = dataclasses.replace(
        self.cfg,
        enabled_toolsets=list(enabled_toolsets),
        disabled_tools=list(disabled_tools) if disabled_tools is not None else list(self.cfg.disabled_tools),
        auto_approve_tools=True,        # forks never block on prompts
        lean_prompt=True,               # keep fork context tight
        max_turn_steps=max_iterations,  # cap fork loop length
    )

    # Defer the Agent construction import to runtime — fork is bound to Agent
    # at module load, so a top-level import here would circle back through core.
    from .core import Agent, _current_agent

    # 2. Construct child agent. Always pass model so cfg.model isn't lost; if
    #    auxiliary_client=False, share the parent's HTTP client to save
    #    sockets (default is a fresh one for true isolation).
    child = Agent(child_cfg, self.workspace, model=self.model)
    if not auxiliary_client:
        try:
            child.client.close()
        except Exception:
            pass
        child.client = self.client

    try:
        # 3. Inject system addendum (preserve messages[0] as the system prompt).
        if system_addendum:
            child.messages[0]["content"] = (
                child.messages[0]["content"].rstrip() + "\n\n" + system_addendum
            )

        # 4. Replace history if provided.
        if conversation_history is not None:
            child.messages = [child.messages[0], *conversation_history]

        result = ForkResult(final_response="")

        def _runner() -> None:
            origin_token = set_current_write_origin(write_origin)
            approval_token = set_approval_callback(AUTO_DENY)
            agent_token = _current_agent.set(child)
            sink = _devnull() if quiet else None
            try:
                if sink is not None:
                    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                        child.run_turn(user_prompt)
                else:
                    child.run_turn(user_prompt)
            except Exception as exc:  # pragma: no cover — defensive
                result.error = f"{type(exc).__name__}: {exc}"
            finally:
                _current_agent.reset(agent_token)
                reset_approval_callback(approval_token)
                reset_current_write_origin(origin_token)
                if sink is not None:
                    try:
                        sink.close()
                    except Exception:
                        pass

        t = threading.Thread(target=_runner, daemon=True, name="ocode-fork")
        t.start()
        t.join()

        # 5. Gather results from child.messages.
        final_text = ""
        tool_calls: list[dict[str, Any]] = []
        for msg in child.messages:
            role = msg.get("role")
            if role == "assistant":
                tcs = msg.get("tool_calls") or []
                tool_calls.extend(tcs)
                content = msg.get("content") or ""
                if content:
                    final_text = content
        if not result.final_response:
            result.final_response = final_text
        result.tool_calls = tool_calls
        return result
    finally:
        try:
            child.close()
        except Exception:
            pass
