"""Per-session running counters consumed by ``/cost``, ``/status``,
and the agent's run_turn bookkeeping.

R1 stage 4 moved this out of :mod:`athena.agent.core` so the
:class:`~athena.agent.lifecycle.AgentLifecycle` mixin can construct
:class:`Stats` from ``__init__`` without a runtime ``lifecycle ->
core`` import cycle (``core`` itself imports ``lifecycle`` for the
inheritance hierarchy).

``Stats`` is still re-exported from :mod:`athena.agent.core` so
existing call sites (``from athena.agent.core import Stats``) keep
working unchanged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Stats:
    """Running counters for the active agent session.

    The first four fields (``prompt_tokens`` / ``eval_tokens`` /
    ``tool_calls`` / ``turns``) plus ``started`` are the original
    Phase 0 shape -- kept for the ``/cost`` slash command and any
    external readers (``tool_call_trace``-style consumers).

    Phase 16 adds per-tool counts + fork / review / curator counters
    and an atomic snapshot writer so ``athena status`` (running in
    a separate process) can read live progress without IPC.
    """

    prompt_tokens: int = 0
    eval_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    started: float = field(default_factory=time.time)
    # Phase 16 additions:
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    fork_count: int = 0
    review_fired_count: int = 0
    curator_run_count: int = 0
    # T2-01: Anthropic prompt-cache counters, populated from the
    # provider's usage chunk. ``cache_read`` is the prefix the API
    # served from cache (cheap); ``cache_creation`` is the new prefix
    # being cached this turn (slightly more expensive than normal
    # input).
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def record_tool_call(self, tool_name: str) -> None:
        """Increment both the top-level counter (legacy ``/cost``)
        and the per-tool histogram used by ``/status``."""
        self.tool_calls += 1
        self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1

    def to_snapshot(
        self,
        *,
        session_id: str | None,
        model: str,
        provider: str,
        profile: str,
        cache_strategy: str | None = None,
        prompt_cache_ttl: str | None = None,
    ) -> dict:
        return {
            "session_id": session_id,
            "model": model,
            "provider": provider,
            "profile": profile,
            "started_at": self.started,
            "elapsed_seconds": time.time() - self.started,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "tool_call_counts": dict(self.tool_call_counts),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.eval_tokens,
            "total_tokens": self.prompt_tokens + self.eval_tokens,
            "fork_count": self.fork_count,
            "review_fired_count": self.review_fired_count,
            "curator_run_count": self.curator_run_count,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_strategy": cache_strategy,
            "prompt_cache_ttl": prompt_cache_ttl,
        }
