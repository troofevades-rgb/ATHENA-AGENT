"""Headless run primitive (T7-01).

Wraps the existing ``Agent`` + ``agent.run_turn(...)`` path into
a batch-friendly primitive: distinct exit codes per outcome,
optional machine-readable JSON envelope, run-id correlation,
wall-clock timeout, file-based task input.

The engine under T7-02 batch_runner — and under any cron job /
gateway dispatcher / external script that wants to drive
athena programmatically.

Public surface:

  :func:`athena.headless.runner.run_headless` — execute one task
  :class:`athena.headless.result.RunResult` — structured outcome
                                              + exit code mapping
"""

from __future__ import annotations

from .result import RunResult, Status
from .runner import run_headless

__all__ = ["RunResult", "Status", "run_headless"]
