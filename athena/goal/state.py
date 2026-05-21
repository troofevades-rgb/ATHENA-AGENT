"""Goal state — the active-driver layer over the passive invariant (T5-07.2).

The passive `/goal` invariant (``goal.txt`` + system-prompt block)
shapes decisions but doesn't drive them. T5-07 adds an *active*
state alongside it: status, turn counter, exhaustion cap, ordered
subgoals.

Two on-disk files per profile:

  ``<profile_dir>/goal.txt``         human-editable objective text
  ``<profile_dir>/goal_state.json``  the machine-managed state

The split is deliberate. The text file stays a single line a human
can ``cat`` or edit; the state file carries the bookkeeping that
the continuation loop needs but the user shouldn't have to read.
Both can be deleted independently; the text file is the source of
truth for the *what*, the state file is the source of truth for
the *how much progress + can we continue*.

Achievement and blocked detection live in :mod:`athena.goal.loop`;
this module is data + persistence only.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


GOAL_STATE_FILENAME = "goal_state.json"

Status = Literal["active", "paused", "achieved", "exhausted"]
_VALID_STATUSES: frozenset[str] = frozenset(
    ("active", "paused", "achieved", "exhausted")
)


@dataclasses.dataclass
class Subgoal:
    """One ordered breadcrumb the model can use to sequence work.

    Subgoals are advisory — the continuation loop doesn't gate on
    them. They're rendered into the goal block so the model knows
    "here are the steps I've broken this into; I marked these ones
    done."

    T6-06.4: each subgoal carries an optional ``task_id`` pointing
    at the matching row in the T6-06.1 task store. When set, the
    board shows the subgoal as a card; flipping done updates both
    sides. None for legacy / fresh subgoals before the projection
    fires.
    """

    text: str
    done: bool = False
    task_id: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"text": self.text, "done": bool(self.done)}
        if self.task_id is not None:
            d["task_id"] = self.task_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Subgoal:
        return cls(
            text=str(d.get("text", "")),
            done=bool(d.get("done", False)),
            task_id=d.get("task_id") or None,
        )


@dataclasses.dataclass
class GoalState:
    """The state of an active goal pursuit.

    Mirror of ``goal.txt`` plus the live bookkeeping:

      ``text``         the objective (kept in sync with goal.txt
                       at write time; reads prefer goal.txt as
                       the human-editable source of truth)
      ``status``       active | paused | achieved | exhausted
      ``turns_taken``  count of continuation cycles that have run
      ``max_turns``    exhaustion cap; loop stops when
                       ``turns_taken >= max_turns``
      ``subgoals``     ordered list of :class:`Subgoal`
      ``created_at``   monotonic epoch seconds at goal creation
      ``updated_at``   monotonic epoch seconds at last mutation
                       (bumped by :func:`save_state`)
    """

    text: str
    status: Status = "active"
    turns_taken: int = 0
    max_turns: int = 25
    subgoals: list[Subgoal] = dataclasses.field(default_factory=list)
    created_at: float = dataclasses.field(default_factory=time.time)
    updated_at: float = dataclasses.field(default_factory=time.time)
    # T6-06.4: stable identifier so the T6-06.1 task store can
    # tag subgoal-cards with goal_id=goal_id. Generated at
    # /goal <text> time (cmd_goal._set_goal_and_state). Empty
    # string for legacy state files; the projection short-
    # circuits when goal_id is empty.
    goal_id: str = ""

    def can_continue(self) -> bool:
        """``True`` iff the continuation loop should keep firing.

        Active status + under the turn cap. The loop's contract is
        that ``can_continue == False`` is the stop signal — any
        non-active status or any cap-met state returns False.
        """
        return self.status == "active" and self.turns_taken < self.max_turns

    def first_pending_subgoal(self) -> Subgoal | None:
        """Return the first not-done subgoal, or None when every
        subgoal is complete (or none exist). Used by
        ``/subgoal done`` to know which one to flip."""
        for sg in self.subgoals:
            if not sg.done:
                return sg
        return None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "status": self.status,
            "turns_taken": int(self.turns_taken),
            "max_turns": int(self.max_turns),
            "subgoals": [sg.to_dict() for sg in self.subgoals],
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
            "goal_id": self.goal_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> GoalState:
        status = d.get("status", "active")
        if status not in _VALID_STATUSES:
            # Fall through to "active" rather than raising — a
            # corrupted status shouldn't lock the user out of
            # their goal.
            logger.debug("unknown goal status %r, normalising to 'active'", status)
            status = "active"
        return cls(
            text=str(d.get("text", "")),
            status=status,  # type: ignore[arg-type]
            turns_taken=int(d.get("turns_taken", 0)),
            max_turns=int(d.get("max_turns", 25)),
            subgoals=[Subgoal.from_dict(sg) for sg in d.get("subgoals", [])],
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
            goal_id=str(d.get("goal_id", "") or ""),
        )

    @classmethod
    def from_json(cls, s: str) -> GoalState:
        return cls.from_dict(json.loads(s))


def state_path(profile_dir: Path) -> Path:
    """Canonical on-disk path for the state JSON of ``profile_dir``."""
    return Path(profile_dir) / GOAL_STATE_FILENAME


def load_state(profile_dir: Path) -> GoalState | None:
    """Read the persisted goal state, or None if absent / unreadable
    / malformed. Defensive — a corrupted state file must not block
    session startup."""
    p = state_path(profile_dir)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("goal state unreadable at %s: %s", p, e)
        return None
    try:
        return GoalState.from_json(raw)
    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
        logger.warning("goal state malformed at %s: %s", p, e)
        return None


def save_state(profile_dir: Path, state: GoalState) -> Path:
    """Persist ``state`` and bump ``updated_at``. Writes the parent
    directory if it doesn't exist (a fresh profile may not have
    one). Returns the on-disk path for the caller's logging."""
    state.updated_at = time.time()
    p = state_path(profile_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(state.to_json(), encoding="utf-8")
    return p


def clear_state(profile_dir: Path) -> bool:
    """Remove the state file. Returns ``True`` if a state file
    existed (i.e. the operation actually deleted something)."""
    p = state_path(profile_dir)
    if not p.exists():
        return False
    p.unlink()
    return True
