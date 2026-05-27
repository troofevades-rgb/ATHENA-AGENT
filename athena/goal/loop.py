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
import subprocess
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


# Bare-minimum kicker used when there's no state to render — the
# original T5-07 default. Production calls go through
# :func:`build_continuation_prompt` which stitches in the goal text,
# turn counter, and subgoal progress so the model sees its own state
# every turn rather than relying on system-prompt context that may
# have been compressed away.
_DEFAULT_CONTINUATION_PROMPT = (
    "Continue working toward the goal. Take one productive step. "
    "When the goal is fully achieved, end your message with a line "
    "containing exactly: GOAL ACHIEVED. If you are blocked and need "
    "the user, end with: GOAL BLOCKED: <reason>."
)


def build_continuation_prompt(
    state: GoalState | None,
    cfg: Any = None,
) -> str:
    """Build the per-turn continuation prompt, stitching in the live
    goal state so the model sees its objective + progress + next
    subgoal directly in the user message (not just buried in the
    system prompt where compaction can hide it).

    Behaviour:

    - ``cfg.goal_continuation_prompt`` (when set + truthy) wins —
      override the whole thing.
    - When ``state`` is None, fall back to the bare kicker (same as
      the historical default).
    - With no subgoals declared yet, the prompt nudges the model to
      decompose the goal first via ``/subgoal <text>`` — this is the
      auto-decompose hint that prevents the model from flailing on a
      multi-step goal it hasn't broken down.
    - With subgoals, the next-incomplete one is surfaced explicitly so
      the model has a concrete pointer for "what now."

    The sentinel contract (``GOAL ACHIEVED`` / ``GOAL BLOCKED: …``) is
    always restated — it's cheap and keeps the model honest about
    completion semantics.
    """
    custom = getattr(cfg, "goal_continuation_prompt", None) if cfg is not None else None
    if custom:
        return str(custom)
    if state is None:
        return _DEFAULT_CONTINUATION_PROMPT

    parts: list[str] = [f"Goal: {state.text}"]
    parts.append(f"Progress: turn {state.turns_taken}/{state.max_turns}")

    subgoals = list(state.subgoals or [])
    done = [sg for sg in subgoals if sg.done]
    pending = [sg for sg in subgoals if not sg.done]

    if subgoals:
        if done:
            tail = ", ".join(sg.text for sg in done[-3:])
            parts.append(f"Recently done ({len(done)}): {tail}")
        if pending:
            parts.append(f"Next subgoal: {pending[0].text}")
            if len(pending) > 1:
                upcoming = "; ".join(sg.text for sg in pending[1:4])
                parts.append(f"Then: {upcoming}")
        else:
            parts.append(
                "All declared subgoals are done — verify the top-level "
                "goal is complete and emit GOAL ACHIEVED, or add the next "
                "subgoal with /subgoal."
            )
    else:
        parts.append(
            "No subgoals declared yet. If this goal has multiple steps, "
            "your FIRST move is to decompose it: call /subgoal <text> for "
            "each concrete step (3–6 is usually right). If it's a "
            "single-step goal, just do it."
        )

    parts.append(
        "Take one productive step now. When the goal is fully achieved, "
        "end your message with a line containing exactly: GOAL ACHIEVED. "
        "If blocked and you need the user, end with: GOAL BLOCKED: <reason>."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Verifier hook (T-GOAL-VERIFY)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class VerifierResult:
    """Outcome of running ``cfg.goal_verifier_command`` after a model
    claims GOAL ACHIEVED. ``passed`` mirrors exit code == 0; ``output``
    carries stderr + stdout (truncated) so the model gets actionable
    feedback when the verifier rejects the claim.
    """

    passed: bool
    output: str


_VERIFIER_OUTPUT_MAX = 4_000


def run_goal_verifier(cfg: Any) -> VerifierResult | None:
    """Run ``cfg.goal_verifier_command`` (when set) and return the
    result. ``None`` means no verifier is configured — caller should
    accept the model's GOAL ACHIEVED claim at face value.

    The command runs through the shell so multi-stage pipelines work
    (``pytest -q && mypy``). Exit code 0 → pass; any other exit code,
    timeout, or spawn failure → fail with the captured reason. Hard
    120-second cap so a runaway verifier can't wedge the loop.
    """
    cmd = getattr(cfg, "goal_verifier_command", None) if cfg is not None else None
    if not cmd:
        return None
    timeout_s = float(getattr(cfg, "goal_verifier_timeout_s", 120.0) if cfg else 120.0)
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        return VerifierResult(
            passed=False,
            output=f"verifier timed out after {timeout_s}s: {e}",
        )
    except OSError as e:
        return VerifierResult(
            passed=False,
            output=f"verifier failed to spawn: {e}",
        )
    output = (proc.stdout or "") + (proc.stderr or "")
    output = output.strip() or "(no output)"
    if len(output) > _VERIFIER_OUTPUT_MAX:
        output = (
            output[: _VERIFIER_OUTPUT_MAX // 2]
            + f"\n... (truncated; {len(output)} chars total) ...\n"
            + output[-_VERIFIER_OUTPUT_MAX // 2 :]
        )
    return VerifierResult(passed=(proc.returncode == 0), output=output)


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
        # Optional verifier guard: when cfg.goal_verifier_command is set,
        # run it before accepting the model's claim. A failing verifier
        # refuses the achievement, keeps the goal active, and injects
        # the verifier's output as the next synthetic prompt so the
        # model knows exactly what's still broken. This is the
        # difference between "I think I'm done" and "tests pass."
        verifier = run_goal_verifier(cfg)
        if verifier is not None and not verifier.passed:
            # Bump turns_taken — the model spent a turn making the
            # claim, and we need turn-cap pressure so a model that
            # keeps emitting GOAL ACHIEVED can't loop forever.
            state.turns_taken += 1
            # Loud UI message: the rejection prompt below goes to the
            # MODEL only; without this, the operator just sees the
            # loop "keep going" with no idea why. The achievement
            # claim and its rejection are real events worth surfacing.
            try:
                from .. import ui as _ui

                preview = (verifier.output or "").splitlines()
                head = preview[0] if preview else "(no output)"
                _ui.warn(
                    f"[goal] verifier rejected GOAL ACHIEVED "
                    f"(turn {state.turns_taken}/{state.max_turns}): {head}"
                )
            except Exception:  # noqa: BLE001
                pass
            if state.turns_taken >= state.max_turns:
                state.status = "exhausted"
                _persist(profile_dir, state)
                return ContinuationDecision(False, stop_reason="exhausted")
            _persist(profile_dir, state)
            rejection = (
                "GOAL ACHIEVED was rejected by the verifier. The goal is "
                "NOT complete. Verifier output:\n"
                f"```\n{verifier.output}\n```\n"
                "Address the failure and continue. Do not re-emit "
                "GOAL ACHIEVED until the verifier passes."
            )
            return ContinuationDecision(True, synthetic_prompt=rejection)
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
    return ContinuationDecision(
        True,
        synthetic_prompt=build_continuation_prompt(state, cfg),
    )


def _persist(profile_dir: Path, state: GoalState) -> None:
    """Best-effort state write. A disk error is logged but never
    re-raised — the loop's in-memory decision is authoritative."""
    try:
        save_state(profile_dir, state)
    except Exception as e:  # noqa: BLE001
        logger.warning("could not persist goal state: %s", e)
