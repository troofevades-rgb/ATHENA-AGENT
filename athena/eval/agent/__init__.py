"""Agent capability eval — pass-rate over tool-using synthetic tasks.

Distinct from the text-eval (``athena.eval`` proper, ``athena eval text``)
which scores ``assistant_text`` against a string/regex/json-path
``expected``. This module verifies what the agent actually DID by
running each task in an isolated ``tempfile.TemporaryDirectory`` and
calling a per-task ``verify_fn`` that inspects the filesystem, the
agent's message history, or a mock MCP server's call log.

The headline number — a single pass-rate for a
``(model, parseltongue_policy, task_set)`` tuple — is the objective
function for comparing base vs LoRA-tuned models and for the future
parseltongue autotune sweep.

Public surface:

  :class:`athena.eval.agent.task.EvalTask`            — one task schema
  :class:`athena.eval.agent.task.VerifyContext`       — passed to verify_fn
  :class:`athena.eval.agent.report.TaskResult`        — one result
  :class:`athena.eval.agent.report.EvalReport`        — aggregate report
  :func:`athena.eval.agent.runner.run_eval`           — main entry
  :func:`athena.eval.agent.runner.run_task`           — single task (for tests)
"""

from __future__ import annotations

from .report import EvalReport, TaskResult, compare_reports
from .runner import run_eval, run_task
from .task import EvalTask, VerifyContext

__all__ = [
    "EvalTask",
    "VerifyContext",
    "TaskResult",
    "EvalReport",
    "run_eval",
    "run_task",
    "compare_reports",
]
