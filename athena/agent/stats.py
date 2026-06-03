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
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# Bounded rolling-window size for latency samples. Large enough to
# give stable percentiles in a normal session (hundreds of turns,
# thousands of tool calls); small enough that a long-lived gateway
# daemon doesn't accumulate unbounded memory. ~2KB per tool at the
# cap (256 floats × 8 bytes).
_LATENCY_WINDOW = 256


def _percentile(samples: list[float], pct: float) -> float:
    """Return the requested percentile from ``samples`` using nearest-
    rank (no interpolation). Empty input returns 0.0.

    Nearest-rank keeps the result exactly one of the recorded
    samples — easier to reason about for diagnostic readers than
    linear interpolation, and we don't need sub-sample precision
    for "is this turn unusually slow" questions.
    """
    if not samples:
        return 0.0
    if pct <= 0:
        return min(samples)
    if pct >= 100:
        return max(samples)
    ordered = sorted(samples)
    # Nearest-rank index: ceil(pct/100 * N) - 1, clamped.
    n = len(ordered)
    idx = int((pct / 100.0) * n)
    if idx >= n:
        idx = n - 1
    return ordered[idx]


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
    # 0.3.0 observability: bounded rolling windows for turn + per-tool
    # latency, plus error counters. The windows give p50/p95/p99 in
    # the /status snapshot so dogfooding regressions ("the model got
    # slower after rebuild X", "tool Y is intermittently hanging")
    # surface without external monitoring. ``deque(maxlen=...)`` caps
    # memory in long-lived gateway sessions.
    turn_durations_ms: deque[float] = field(default_factory=lambda: deque(maxlen=_LATENCY_WINDOW))
    tool_durations_ms: dict[str, deque[float]] = field(default_factory=dict)
    provider_errors: int = 0
    tool_errors: int = 0

    def record_tool_call(self, tool_name: str) -> None:
        """Increment both the top-level counter (legacy ``/cost``)
        and the per-tool histogram used by ``/status``."""
        self.tool_calls += 1
        self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1

    def record_turn_duration(self, seconds: float) -> None:
        """Append a turn-latency sample (seconds) to the rolling
        window in ms. Callers are expected to time the full
        ``_run_turn_inner`` body."""
        self.turn_durations_ms.append(seconds * 1000.0)

    def record_tool_duration(self, tool_name: str, seconds: float) -> None:
        """Append a per-tool latency sample. Buckets are lazy-
        created so unseen tools don't take space until they fire."""
        bucket = self.tool_durations_ms.get(tool_name)
        if bucket is None:
            bucket = deque(maxlen=_LATENCY_WINDOW)
            self.tool_durations_ms[tool_name] = bucket
        bucket.append(seconds * 1000.0)

    def record_provider_error(self) -> None:
        """Increment the provider-error counter -- one per caught
        exception in the streaming path. A non-zero count in
        ``/status`` is a strong signal something is wrong with the
        model endpoint."""
        self.provider_errors += 1

    def record_tool_error(self) -> None:
        """Increment the tool-error counter -- one per tool dispatch
        that raised. Distinct from tool results that *contain* error
        strings (which we can't reliably classify)."""
        self.tool_errors += 1

    def _latency_summary(self, samples: deque[float]) -> dict[str, float | int]:
        """Compute count + p50/p95/p99 from a rolling window."""
        as_list = list(samples)
        return {
            "count": len(as_list),
            "p50_ms": _percentile(as_list, 50),
            "p95_ms": _percentile(as_list, 95),
            "p99_ms": _percentile(as_list, 99),
        }

    def to_snapshot(
        self,
        *,
        session_id: str | None,
        model: str,
        provider: str,
        profile: str,
        cache_strategy: str | None = None,
        prompt_cache_ttl: str | None = None,
    ) -> dict[str, Any]:
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
            # 0.3.0 observability: rolling-window latency + error
            # counters. ``turn_latency_ms`` / ``tool_latencies_ms``
            # are None / empty until the agent has recorded at
            # least one sample (so a fresh session's /status
            # doesn't show p50=0.0 noise).
            "turn_latency_ms": (
                self._latency_summary(self.turn_durations_ms) if self.turn_durations_ms else None
            ),
            "tool_latencies_ms": {
                name: self._latency_summary(window)
                for name, window in self.tool_durations_ms.items()
                if window
            },
            "provider_errors": self.provider_errors,
            "tool_errors": self.tool_errors,
        }
