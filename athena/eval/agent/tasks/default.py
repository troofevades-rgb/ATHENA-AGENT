"""Default task set + user-task discovery.

``TASKS`` is the canonical default set — the four buckets stitched
together for the eval CLI's ``--tasks default`` choice. Total: 50
tasks (15 file_ops + 15 shell + 10 structured + 10 mcp).

User-supplied task modules under ``~/.athena/eval_tasks/*.py`` are
discovered at runtime by :func:`discover_user_tasks` so operators
can extend the catalog without forking athena.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from ..task import EvalTask
from . import file_ops, mcp, shell, structured

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical default set
# ---------------------------------------------------------------------------


TASKS: list[EvalTask] = [
    *file_ops.TASKS,
    *shell.TASKS,
    *structured.TASKS,
    *mcp.TASKS,
]


# ---------------------------------------------------------------------------
# Per-bucket access — used by ``--tasks file_ops`` etc.
# ---------------------------------------------------------------------------


BUCKETS: dict[str, list[EvalTask]] = {
    "default": TASKS,
    "file_ops": file_ops.TASKS,
    "shell": shell.TASKS,
    "structured": structured.TASKS,
    "mcp": mcp.TASKS,
}


def get_task_set(name: str) -> list[EvalTask]:
    """Resolve a task-set name to its task list.

    - Built-in names: ``default``, ``file_ops``, ``shell``,
      ``structured``, ``mcp``.
    - Otherwise treated as a user-supplied module name discovered
      under ``~/.athena/eval_tasks/``.

    Raises ``KeyError`` with the available names listed when
    nothing matches."""
    if name in BUCKETS:
        return BUCKETS[name]
    user = discover_user_tasks()
    if name in user:
        return user[name]
    available = sorted(BUCKETS) + sorted(user)
    raise KeyError(
        f"unknown task set {name!r}. Available: {', '.join(available)}"
    )


# ---------------------------------------------------------------------------
# User-task discovery
# ---------------------------------------------------------------------------


def _user_tasks_dir() -> Path:
    """Resolve ``~/.athena/eval_tasks/`` dynamically so test isolation
    via monkeypatched ``Path.home`` propagates correctly. Computing
    this at module-import time would freeze the developer's real
    home into a constant (the same bug the test_store_path_leak
    fix in athena/tools/task.py guards against)."""
    return Path.home() / ".athena" / "eval_tasks"


def discover_user_tasks() -> dict[str, list[EvalTask]]:
    """Load every ``*.py`` under ``~/.athena/eval_tasks/`` as a
    task-set module. Each module must export ``TASKS: list[EvalTask]``.

    Returns a dict mapping ``<filename without .py>`` → ``TASKS``.
    Modules that fail to import are LOGGED and skipped — one broken
    file shouldn't take down the whole catalog.
    """
    root = _user_tasks_dir()
    if not root.is_dir():
        return {}

    out: dict[str, list[EvalTask]] = {}
    for py in sorted(root.glob("*.py")):
        if py.name.startswith("_"):
            continue  # skip __init__.py, _helpers.py, etc.
        mod_name = f"athena_user_eval_tasks.{py.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            tasks = getattr(module, "TASKS", None)
            if not isinstance(tasks, list):
                logger.warning(
                    "user eval-task module %s has no TASKS list", py
                )
                continue
            # Reject anything that isn't actually an EvalTask.
            valid = [t for t in tasks if isinstance(t, EvalTask)]
            if valid:
                out[py.stem] = valid
            else:
                logger.warning(
                    "user eval-task module %s exports TASKS but no entries are EvalTask", py
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "user eval-task module %s failed to import: %s", py, e
            )
            continue
    return out


__all__ = ["TASKS", "BUCKETS", "get_task_set", "discover_user_tasks"]
