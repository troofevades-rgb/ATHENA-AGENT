"""Auto kanban — persisted task store + board projection (T6-06).

Single backing store for two surfaces:

  * The existing :mod:`athena.tools.task` TaskCreate / TaskUpdate /
    TaskList tools — backed by this store (T6-06.2 wires this).
    Tool API stays the same; only persistence is added.
  * Goal-loop subgoals (T5-07) — projected into this store as
    tasks with ``goal_id`` set (T6-06.4 wires this).

The board (:mod:`athena.tasks.board`) is a column projection
over the store. The store is the truth; the board is a view.
"""

from .model import Status, Task, TaskStore, default_task_store_path

__all__ = ["Status", "Task", "TaskStore", "default_task_store_path"]
