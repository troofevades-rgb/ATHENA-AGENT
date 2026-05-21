"""Batch runner (T7-02).

Iterates T7-01's :func:`athena.headless.run_headless` over a
list of tasks read from JSONL. Per-run envelopes land on disk;
a batch ``manifest.json`` aggregates the run.

Composes naturally with cron jobs, the Phase 7 training-loop
trajectory generator, and the future T7-03 eval-battery —
anything that wants "drive athena over N tasks and tell me
what happened" gets it from one composable engine.

Public surface:

  :func:`athena.batch.runner.batch_run`     — execute a batch
  :class:`athena.batch.manifest.BatchEntry` — one input task
  :class:`athena.batch.manifest.BatchManifest` — aggregated outcome
"""

from __future__ import annotations

from .manifest import BatchEntry, BatchManifest
from .runner import batch_run, parse_tasks_file

__all__ = [
    "BatchEntry",
    "BatchManifest",
    "batch_run",
    "parse_tasks_file",
]
