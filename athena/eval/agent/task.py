"""Task schema for the agent capability eval.

A task is a deterministic capability probe: setup the world, give
the agent a prompt, then check whether the agent's actions changed
the world in the expected way.

Distinct from ``athena.eval.summary.EvalCase`` (text-eval) — that
scores ``assistant_text`` against an ``expected`` string. This
schema doesn't care what the agent SAID; it cares what the agent
DID.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# VerifyContext — what verify_fn sees after the agent has run
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class VerifyContext:
    """The full post-run state available to ``verify_fn``.

    ``verify_fn`` returns ``True`` iff the task passed.

    - **workspace**: the temp dir the agent ran in. Walk it to check
      filesystem side-effects (created/renamed/edited files, git state).
    - **agent_messages**: the agent's full message history. Inspect
      assistant_text for structured-output tasks, or scan for the
      presence/absence of specific tool calls.
    - **tool_calls**: flat list of every tool call the agent made
      (mirror of ``Agent.tool_call_trace()``). Use to verify the
      RIGHT tool was called with the RIGHT args, not just that
      *some* tool was called.
    - **mcp_call_log**: a list of ``{tool, args, result}`` records
      from any mock MCP server the task spun up. Empty for
      non-MCP tasks. The runner injects this when a task declares
      a mock server in its setup.
    """

    workspace: Path
    agent_messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    mcp_call_log: list[dict[str, Any]] = dataclasses.field(default_factory=list)


# Type aliases for clarity at task-definition sites.
SetupFn = Callable[[Path], None]
VerifyFn = Callable[[VerifyContext], bool]


# ---------------------------------------------------------------------------
# EvalTask — one capability probe
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class EvalTask:
    """One synthetic capability probe.

    Required:
      - ``id``: stable identifier. Forms the basis for cross-run diffs.
      - ``prompt``: the user input given to the agent.
      - ``setup_fn``: populate the temp workspace before the agent runs.
      - ``verify_fn``: return True iff the task passed.

    Optional:
      - ``timeout_s``: hard wall-clock cap. Default 60s. A task that
        exceeds is failed-closed and the suite continues — never block
        the eval run on a single hung task.
      - ``required_tools``: toolset names the agent needs. Used by
        ``run_task`` to set ``cfg.enabled_toolsets``; empty = all
        enabled by default.
      - ``bucket``: category for per-bucket pass-rate reporting
        (``file_ops`` / ``shell`` / ``structured`` / ``mcp`` / ...).
        Defaults to ``general`` for tasks that don't declare one.
      - ``description``: one-line human summary for ``list-tasks``
        output. Optional; falls back to a truncated prompt.
      - ``mcp_servers``: optional list of mock MCP server factories
        the runner will spin up before the agent boots. Each factory
        is a ``Callable[[Path], MockMCPServer]`` (see ``mcp.py``).
        Empty for non-MCP tasks.
    """

    id: str
    prompt: str
    setup_fn: SetupFn
    verify_fn: VerifyFn
    timeout_s: float = 60.0
    required_tools: list[str] = dataclasses.field(default_factory=list)
    bucket: str = "general"
    description: str = ""
    mcp_servers: list[Callable[[Path], Any]] = dataclasses.field(
        default_factory=list
    )

    def short_description(self) -> str:
        """One-line summary for catalog displays. Prefers ``description``
        when set; falls back to truncated ``prompt``."""
        if self.description:
            return self.description
        text = self.prompt.strip().replace("\n", " ")
        return text if len(text) <= 80 else text[:77] + "..."

    def to_catalog_dict(self) -> dict[str, Any]:
        """JSON-safe summary suitable for ``athena eval list-tasks``.
        Excludes the callables — they're not serializable and a
        catalog listing doesn't need them."""
        return {
            "id": self.id,
            "bucket": self.bucket,
            "description": self.short_description(),
            "timeout_s": self.timeout_s,
            "required_tools": list(self.required_tools),
            "uses_mcp": bool(self.mcp_servers),
        }


__all__ = ["EvalTask", "VerifyContext", "SetupFn", "VerifyFn"]
