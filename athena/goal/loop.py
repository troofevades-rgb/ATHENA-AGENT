"""Continuation loop — sentinel detection + per-turn decision (T5-07.3).

Two halves:

  :func:`scan_sentinels` — read the assistant's last turn text;
    return ``(achieved, blocked_reason)``. The regexes are
    case-insensitive and tolerant of common markdown leading bytes
    (``#``, ``>``, ``*``, whitespace) so the model's natural
    formatting doesn't break the contract.

  :func:`maybe_continue_goal_after_turn` — the per-turn driver.
    Given the current :class:`GoalState` + the assistant's text,
    it decides ``ContinuationDecision(should_continue=...)`` and
    persists any state mutation (turns_taken bump, status flip).
    The caller (Agent core, gateway) reads ``should_continue``
    + ``synthetic_prompt`` and either injects a fake user turn or
    stops with the surfaced ``stop_reason``.

Why sentinels instead of a "done?" classifier:

  A sentinel is deterministic and cheap — no extra model call,
  no extra failure mode, no extra latency. The contract is in
  the goal block (T5-07.4); the model emits the line; the loop
  greps for it. Achievement is the *model's* call, verified by
  the sentinel — the loop never decides the goal is done on
  its own.

The runaway risk is the whole reason for the caps in
:meth:`GoalState.can_continue` and the per-token budget the
caller layer enforces; see ``docs/reference/goal.md`` for the
full safety model.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import Any

from .state import GoalState, save_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinel regexes
# ---------------------------------------------------------------------------

# Optional markdown lead-in (#, >, *, list bullets) + whitespace at the
# start of a line, then the literal sentinel. ACHIEVED is a whole line;
# BLOCKED captures the reason after the colon.
#
# Both are MULTILINE so the contract is "any line in the assistant's
# message" — the spec says "end your message with the line", but a
# friendlier scanner accepts the sentinel anywhere on its own line so
# a trailing markdown rendering quirk doesn't lose us achievement.
#
# The DOTALL is intentionally NOT set; the reason capture stops at the
# end of its line so multi-paragraph blocked messages don't slurp the
# whole tail into ``reason``.

_LEAD = r"^\s*[>#*\-•]*\s*"

_ACHIEVED_RX = re.compile(
    _LEAD + r"GOAL\s+ACHIEVED\b[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)

_BLOCKED_RX = re.compile(
    _LEAD + r"GOAL\s+BLOCKED\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclasses.dataclass
class ContinuationDecision:
    """Result of one continuation decision.

    ``should_continue``      True → caller injects a synthetic turn
    ``synthetic_prompt``     populated when ``should_continue`` is True
    ``stop_reason``          set when ``should_continue`` is False:
                              "achieved" | "blocked" | "exhausted" |
                              "paused" | "disabled" | "no_state"
    ``blocked_reason``       reason captured from a GOAL BLOCKED line
                              (None for other stop_reasons)
    """

    should_continue: bool
    synthetic_prompt: str | None = None
    stop_reason: str | None = None
    blocked_reason: str | None = None


# Default continuation prompt — kept short on purpose. The full
# sentinel contract is documented in the goal block T5-07.4 writes;
# this turn-by-turn nudge just reminds the model to keep going AND
# to use the existing sentinels when done or blocked. Override via
# ``cfg.goal_continuation_prompt``.
_DEFAULT_CONTINUATION_PROMPT = (
    "Continue working toward the goal. Take one productive step. "
    "When the goal is fully achieved, end your message with a line "
    "containing exactly: GOAL ACHIEVED. If you are blocked and need "
    "the user, end with: GOAL BLOCKED: <reason>."
)


# ---------------------------------------------------------------------------
# Sentinel scanner
# ---------------------------------------------------------------------------


def scan_sentinels(assistant_text: str) -> tuple[bool, str | None]:
    """Return ``(achieved, blocked_reason)``.

    - ``achieved`` is True iff the assistant text contains a
      "GOAL ACHIEVED" line (case-insensitive, optional markdown
      lead-in). Achievement wins over blocked when both appear —
      the model committed to "done" so the loop honours that.
    - ``blocked_reason`` is the reason text after "GOAL BLOCKED:",
      stripped of surrounding whitespace, or None.

    Empty / non-string input → ``(False, None)`` rather than an
    exception, so a degenerate streaming turn doesn't crash the
    loop.
    """
    if not assistant_text or not isinstance(assistant_text, str):
        return False, None
    if _ACHIEVED_RX.search(assistant_text):
        return True, None
    m = _BLOCKED_RX.search(assistant_text)
    if m:
        reason = m.group(1).strip()
        return False, reason or None
    return False, None


# ---------------------------------------------------------------------------
# Continuation decision
# ---------------------------------------------------------------------------


def maybe_continue_goal_after_turn(
    *,
    profile_dir: Path,
    state: GoalState | None,
    last_assistant_text: str,
    cfg: Any,
) -> ContinuationDecision:
    """Decide whether to inject a synthetic continuation turn.

    Mutates and persists ``state`` when the outcome bumps the turn
    counter or flips the status. Persistence is best-effort — a
    write failure is logged but doesn't change the in-memory
    decision (so the agent isn't stuck because of a disk hiccup).

    Branches:

      no state                 → ``no_state`` (no goal active;
                                 nothing to drive)
      cfg disabled             → ``disabled``
      achieved sentinel        → status="achieved"; ``achieved``
      blocked sentinel         → status="paused"; ``blocked`` +
                                 ``blocked_reason``
      state.status != active   → that status as the stop_reason
                                 (paused / achieved / exhausted —
                                 the caller already saw this state)
      turn cap reached         → status="exhausted"; ``exhausted``
      else                     → bump turns_taken; should_continue=True;
                                 synthetic_prompt set
    """
    if state is None:
        return ContinuationDecision(False, stop_reason="no_state")
    if not getattr(cfg, "goal_loop_enabled", True):
        return ContinuationDecision(False, stop_reason="disabled")

    achieved, blocked_reason = scan_sentinels(last_assistant_text)
    if achieved:
        state.status = "achieved"
        _persist(profile_dir, state)
        return ContinuationDecision(False, stop_reason="achieved")
    if blocked_reason is not None:
        state.status = "paused"
        _persist(profile_dir, state)
        return ContinuationDecision(
            False,
            stop_reason="blocked",
            blocked_reason=blocked_reason,
        )

    # No sentinel — consult state. A paused / achieved / exhausted
    # state means the loop is already stopped; reflect that to the
    # caller without further mutation.
    if state.status != "active":
        return ContinuationDecision(False, stop_reason=state.status)

    # Bump first; check cap on the NEW value so the test
    # "max_turns=1 → exhausts on first call" is honest about
    # turns_taken (=1, not 0).
    state.turns_taken += 1
    if state.turns_taken >= state.max_turns:
        state.status = "exhausted"
        _persist(profile_dir, state)
        return ContinuationDecision(False, stop_reason="exhausted")

    _persist(profile_dir, state)
    prompt = (
        getattr(cfg, "goal_continuation_prompt", None)
        or _DEFAULT_CONTINUATION_PROMPT
    )
    return ContinuationDecision(True, synthetic_prompt=prompt)


def _persist(profile_dir: Path, state: GoalState) -> None:
    """Best-effort state write. A disk error is logged but never
    re-raised — the loop's in-memory decision is authoritative."""
    try:
        save_state(profile_dir, state)
    except Exception as e:  # noqa: BLE001
        logger.warning("could not persist goal state: %s", e)
