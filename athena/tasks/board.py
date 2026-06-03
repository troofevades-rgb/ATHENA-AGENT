"""Board view + ``board_show`` tool (T6-06.3).

The board is a **projection** over the T6-06.1 task store:
``project_board(store, ...)`` slices the model into columns,
nothing more. The store is the truth; the board is a view.

Two surfaces consume the projection:

  1. The model-callable ``board_show`` tool — returns JSON
     so the agent can read its own kanban during a goal run.
  2. The ``athena board`` TUI (T6-06.3 / docs/reference/board.md) —
     reads the same projection.

Workspace + goal_id filters compose; passing both gives "this
goal's cards in this workspace".
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ..tools.registry import tool
from .model import Status, Task, TaskStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure projection
# ---------------------------------------------------------------------------


# Display order — left → right columns on the board. Kept in
# sync with TaskStore's _STATUS_ORDER.
_COLUMNS: tuple[Status, ...] = ("todo", "doing", "blocked", "done")


def project_board(
    store: TaskStore,
    *,
    workspace: str | None = None,
    goal_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Slice the store into columns. Each column is a list of
    card dicts ordered by the store's per-column ``order``.

    Card shape::

      {
        "id":         "t-abc123def456",
        "title":      "implement feature",
        "goal_id":    null,        # populated when subgoal
        "parent_id":  null,        # populated for subtasks
        "order":      0,
        "note":       "...",
        "created_at": 1234567890.0,
        "updated_at": 1234567900.0
      }

    Returns a dict keyed by status with EVERY column present
    (empty list when nothing in that column) so the renderer
    doesn't have to handle missing keys.
    """
    tasks = store.list(workspace=workspace, goal_id=goal_id)
    cols: dict[str, list[dict[str, Any]]] = {c: [] for c in _COLUMNS}
    for t in tasks:
        col = cols.setdefault(t.status, [])
        col.append(
            {
                "id": t.id,
                "title": t.title,
                "goal_id": t.goal_id,
                "parent_id": t.parent_id,
                "order": t.order,
                "note": t.note,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
        )
    # ``store.list`` already sorts by order within each column,
    # so no resort needed here.
    return cols


def column_counts(cols: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """{col: count} convenience for status renders."""
    return {c: len(cols.get(c, [])) for c in _COLUMNS}


# ---------------------------------------------------------------------------
# board_show tool
# ---------------------------------------------------------------------------


@tool(
    name="board_show",
    toolset="tasks",
    description=(
        "Show the current kanban board — the same tasks "
        "TaskCreate/TaskUpdate/TaskList manage, organised as "
        "todo / doing / blocked / done columns. Returns JSON. "
        "Optional goal_id filters to a single goal's cards "
        "(when the board is being used to track a /goal run)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "goal_id": {
                "type": "string",
                "description": (
                    "Filter to a single goal's cards. Omit for every card in the workspace."
                ),
            },
        },
    },
    parallel_safe=True,
)
def board_show(goal_id: str | None = None, **_kwargs: Any) -> str:
    """Tool entry. Builds the projection against the cached
    TaskStore that the TaskCreate / TaskUpdate / TaskList tools
    share — single backing store, same view."""
    from ..tools.task import _resolve_store, _resolve_workspace

    store = _resolve_store()
    workspace = _resolve_workspace() or None
    cols = project_board(
        store,
        workspace=workspace,
        goal_id=goal_id or None,
    )
    payload = {
        "workspace": workspace,
        "goal_id": goal_id or None,
        "counts": column_counts(cols),
        "columns": cols,
    }
    return json.dumps(payload, ensure_ascii=False)
