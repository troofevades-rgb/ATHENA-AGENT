"""The observe-act loop — the ONLY call site of backend.perform (T6-04.5).

Contract enforced in this file (and pinned by tests):

  At the TOP of every iteration:
    1. Poll the kill switch — engaged → halt + audit + stop.
    2. Hit the actions-per-task cap → stop with "max_actions".
    3. Hit the no-op detection (screen unchanged after N action
       cycles) → stop and surface "stuck".

  Then:
    4. Take a screenshot via the backend (observe; never gated).
    5. Ask the model for the next proposed action (vision call;
       injectable so tests don't need a real vision provider).
    6. If the model signalled done → stop with "done".
    7. Classify the proposed action.
    8. Run it through the permission gate. Denied → log +
       (configurably) tell the model + continue.
    9. ONLY when the gate returns True: perform the action via
       backend.perform(). This is the single call site of
       perform() in athena's entire codebase.
   10. Rate-limit: sleep 1/computer_max_actions_per_sec.
   11. Repeat.

The propose-next-action function is injectable so the same loop
runs the production path (vision model proposes), a dry-run
path (T6-04.6 — propose but never perform), and tests.

Coordinate mapping (logical → physical pixels):

  Screenshots report a ``scale`` factor (1.0 at 96 DPI; 2.0 on
  retina; 1.5 on common Windows fractional-DPI). The model
  proposes coordinates in the screenshot's pixel space; the
  loop maps them to backend pixel space via :func:`map_coords`.
  Same-space backends (scale == 1.0) round-trip unchanged. A
  mis-mapped click is a safety issue (clicking a wrong button),
  so this is one of the few pure-function pieces with its own
  test.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from typing import Any, Optional

from . import killswitch
from .audit import ActionAuditLog
from .contract import Action, Screenshot
from .permission import PermissionGate, classify

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Proposal model
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ActionProposal:
    """One step the vision model returned.

    ``done`` ends the loop with status="done"; ``action`` is
    what to attempt next when not done. ``message`` is optional
    context (the model's narration) audit-logged alongside.
    """

    done: bool
    action: Action | None = None
    message: str | None = None


ProposeFn = Callable[[str, Screenshot, list[Any]], ActionProposal]
"""Vision dispatcher signature: (task, screenshot, history) →
proposal. ``history`` is the list of audit-entry summaries from
prior iterations so the model has loop context. The injection
point keeps loop.py free of any vision-provider import."""


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LoopResult:
    """Outcome of one computer_do task."""

    status: str  # done | halted | max_actions | stuck | error | denied_first
    actions_taken: int
    halt_reason: str | None = None
    last_message: str | None = None


# ---------------------------------------------------------------------------
# Coordinate mapping
# ---------------------------------------------------------------------------


def map_coords(
    coords: tuple[int, int] | None,
    *,
    screenshot: Screenshot,
) -> tuple[int, int] | None:
    """Translate model-proposed (in screenshot pixel space) to
    backend pixel space.

    The screenshot already IS in backend pixel space — the
    ``scale`` carried with it describes the DPI factor for any
    downstream renderer (e.g. a vision provider that resamples
    the image). For our purposes the screenshot pixels and the
    backend pixels are the same coordinate system; we just
    clamp to bounds to defend against an off-screen click.

    Returns the clamped coordinates, or None when ``coords`` is
    None. An out-of-bounds proposal that we clamp also logs a
    warning — these often indicate model confusion and the
    operator should see it.
    """
    if coords is None:
        return None
    x, y = int(coords[0]), int(coords[1])
    cx, cy = x, y
    max_x = max(0, screenshot.width - 1)
    max_y = max(0, screenshot.height - 1)
    if cx < 0:
        cx = 0
    elif cx > max_x:
        cx = max_x
    if cy < 0:
        cy = 0
    elif cy > max_y:
        cy = max_y
    if (cx, cy) != (x, y):
        logger.warning(
            "computer loop: clamped out-of-bounds coords (%d,%d) → (%d,%d)",
            x,
            y,
            cx,
            cy,
        )
    return (cx, cy)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def computer_do(
    task: str,
    *,
    backend: Any,
    gate: PermissionGate,
    propose: ProposeFn,
    audit: ActionAuditLog,
    cfg: Any,
    dry_run: bool = False,
) -> LoopResult:
    """Run the observe-act loop until the task signals done, a
    cap fires, or the kill switch engages.

    Parameters intentionally injected (no module-level globals):

      backend    DesktopBackend with screenshot + perform
      gate       PermissionGate — the only authority on whether
                 an action runs
      propose    vision-callable that returns the next
                 ActionProposal for (task, screenshot, history)
      audit      ActionAuditLog appender
      cfg        config — reads max_actions_per_task,
                 max_actions_per_sec
      dry_run    when True, every gate-allowed action is logged
                 BUT backend.perform is not called. T6-04.6
                 surfaces this flag from cfg.computer_dry_run.
    """
    computer = getattr(cfg, "computer", None)
    if computer is not None:
        killswitch.arm(hotkey=computer.kill_hotkey)
        max_actions = int(computer.max_actions_per_task)
        max_per_sec = float(computer.max_actions_per_sec)
    else:
        killswitch.arm(hotkey=None)
        max_actions = 40
        max_per_sec = 2.0
    delay = 1.0 / max_per_sec if max_per_sec > 0 else 0.0
    history: list[dict[str, Any]] = []
    actions_taken = 0
    last_screenshot_hash: str | None = None
    unchanged_count = 0
    NOOP_THRESHOLD = 4  # screen unchanged after N attempts → stuck

    try:
        while True:
            # 1. Kill switch — checked TOP of every iteration.
            decision = killswitch.poll_for_halt()
            if decision.halted:
                logger.warning("computer loop: halted by kill switch (%s)", decision.reason)
                _log_halt(audit, decision.reason or "kill switch")
                return LoopResult(
                    status="halted",
                    actions_taken=actions_taken,
                    halt_reason=decision.reason,
                )

            # 2. Cap enforcement.
            if actions_taken >= max_actions:
                logger.info("computer loop: reached max actions/task (%d)", max_actions)
                return LoopResult(
                    status="max_actions",
                    actions_taken=actions_taken,
                )

            # 3. Observe.
            try:
                shot = backend.screenshot()
            except Exception as e:  # noqa: BLE001
                logger.warning("computer loop: screenshot failed: %s", e)
                return LoopResult(
                    status="error",
                    actions_taken=actions_taken,
                    halt_reason=f"screenshot failed: {e}",
                )

            # 3b. No-op detection — screen unchanged across N
            # iterations means the model is probably stuck
            # clicking nothing useful. Bail out + audit.
            from .audit import hash_screenshot

            shot_hash = hash_screenshot(shot)
            if shot_hash == last_screenshot_hash:
                unchanged_count += 1
                if unchanged_count >= NOOP_THRESHOLD:
                    logger.warning(
                        "computer loop: %d iterations with no screen change — stuck",
                        unchanged_count,
                    )
                    return LoopResult(
                        status="stuck",
                        actions_taken=actions_taken,
                        halt_reason=(f"screen unchanged after {unchanged_count} attempts"),
                    )
            else:
                unchanged_count = 0
                last_screenshot_hash = shot_hash

            # 4. Propose.
            try:
                proposal = propose(task, shot, history)
            except Exception as e:  # noqa: BLE001
                logger.warning("computer loop: propose() raised: %s", e)
                return LoopResult(
                    status="error",
                    actions_taken=actions_taken,
                    halt_reason=f"vision proposal failed: {e}",
                )

            if proposal.done:
                return LoopResult(
                    status="done",
                    actions_taken=actions_taken,
                    last_message=proposal.message,
                )

            action = proposal.action
            if action is None:
                # Model neither finished nor proposed — surface
                # as stuck so the operator sees the loop didn't
                # silently spin.
                return LoopResult(
                    status="stuck",
                    actions_taken=actions_taken,
                    halt_reason="vision returned no action",
                )

            # Inject the live foreground app (the model may not
            # know it; the gate needs it for allow/denylist).
            if action.app is None:
                try:
                    action.app = backend.active_app()
                except Exception:  # noqa: BLE001
                    action.app = None
            # Coord mapping + clamping.
            action.coords = map_coords(action.coords, screenshot=shot)

            # 5. Classify + gate. THE SAFETY BOUNDARY.
            tier = classify(action)
            allowed = gate.check(action)

            audit.log(
                action=action,
                tier=tier,
                confirmed=allowed if action.is_input else None,
                executed=allowed and not dry_run,
                screenshot=shot,
                result=(
                    "ok" if allowed and not dry_run else "denied" if not allowed else "dry-run"
                ),
            )
            history.append(
                {
                    "type": action.type,
                    "target": action.target_desc,
                    "tier": tier,
                    "allowed": allowed,
                    "message": proposal.message,
                }
            )

            if not allowed:
                # Continue — let the model adapt. Don't perform.
                continue

            # 6. THE ONLY CALL SITE of backend.perform.
            if not dry_run:
                try:
                    backend.perform(action)
                except Exception as e:  # noqa: BLE001
                    logger.warning("computer loop: backend.perform failed: %s", e)
                    return LoopResult(
                        status="error",
                        actions_taken=actions_taken,
                        halt_reason=f"perform failed: {e}",
                    )
            actions_taken += 1

            # 7. Rate-limit.
            if delay > 0:
                # Killswitch-aware sleep so a halt during the
                # rate-limit sleep is honoured promptly.
                _sleep_with_halt_check(delay)
    finally:
        # Loop cleanup: reset the per-session permission grant
        # so the NEXT task re-confirms, and disengage the
        # killswitch so its SIGINT handler doesn't outlive the
        # loop.
        gate.reset_session()
        killswitch.disengage()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _log_halt(audit: ActionAuditLog, reason: str) -> None:
    """Record the halt event itself so the audit row exists
    even when no in-progress action triggered it."""
    audit.log(
        action=Action(type="screenshot"),  # placeholder; halts don't have an action
        tier="observe",
        confirmed=None,
        executed=False,
        screenshot=None,
        result=f"halted: {reason}",
    )


def _sleep_with_halt_check(total: float) -> None:
    """Sleep up to ``total`` seconds, checking the kill switch
    every 50ms so a halt during the rate-limit pause is
    responsive."""
    SLICE = 0.05
    waited = 0.0
    while waited < total:
        if killswitch.is_engaged():
            return
        chunk = min(SLICE, total - waited)
        time.sleep(chunk)
        waited += chunk
