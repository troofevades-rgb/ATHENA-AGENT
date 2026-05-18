"""Stable metric instrument names — exported separately so
dashboards can reference them without depending on the plugin's
runtime state."""
from __future__ import annotations


METRIC_TOOL_CALL_COUNT = "athena.tool_call.count"
"""Counter — tool calls per (tool_name, status)."""

METRIC_TOOL_CALL_LATENCY = "athena.tool_call.latency_ms"
"""Histogram — wall-clock duration of a tool call in ms."""

METRIC_FORK_COUNT = "athena.fork.count"
"""Counter — sub-agent forks (background review, curator, sub-agent
delegation). One increment per fork; the ``kind`` attribute carries
which path fired it."""

METRIC_TURN_COUNT = "athena.turn.count"
"""Counter — completed user turns."""

METRIC_TURN_LATENCY = "athena.turn.latency_ms"
"""Histogram — total wall-clock time for a single user turn."""

METRIC_PROMPT_TOKENS = "athena.tokens.prompt"
"""Counter — prompt tokens consumed."""

METRIC_COMPLETION_TOKENS = "athena.tokens.completion"
"""Counter — completion tokens emitted."""


__all__ = [
    "METRIC_TOOL_CALL_COUNT",
    "METRIC_TOOL_CALL_LATENCY",
    "METRIC_FORK_COUNT",
    "METRIC_TURN_COUNT",
    "METRIC_TURN_LATENCY",
    "METRIC_PROMPT_TOKENS",
    "METRIC_COMPLETION_TOKENS",
]
