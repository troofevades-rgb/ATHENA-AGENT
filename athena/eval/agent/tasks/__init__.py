"""Synthetic task catalogue for the agent capability eval.

Each module in this package exposes a ``TASKS: list[EvalTask]``
list. The default task set (``default.TASKS``) aggregates the
per-bucket modules so a single call to :func:`run_eval` against
``default.TASKS`` exercises the whole battery.

Buckets:
  - :mod:`.file_ops`   — create / rename / edit / find-and-modify
  - :mod:`.shell`      — count, build dir trees, git
  - :mod:`.structured` — emit JSON-shaped / markdown output
  - :mod:`.mcp`        — mock MCP server interactions
"""
