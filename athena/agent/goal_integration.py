"""Goal-loop integration mixin for :class:`~athena.agent.core.Agent`.

R1 stage 1 pilot of the inheritance split. ``AgentGoalIntegration``
owns the agent-side goal hooks -- the after-turn continuation
decision (``_consult_goal_continuation``) and the best-effort state
persistence call (``_persist_goal_state``). Both methods stay
methods (no signature change) so the mixin slots into ``Agent``'s
MRO without touching any caller. Subsequent stages will pull the
lifecycle and runtime methods into their own mixins the same way.

This module intentionally has no imports of :mod:`athena.agent.core`
-- the mixin is loaded by ``core`` itself when it builds the
``Agent`` class. The TYPE_CHECKING-only block keeps the type
annotations on attributes accessed via ``self`` accurate without
introducing a circular import.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .. import ui

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..goal.state import GoalState

logger = logging.getLogger(__name__)


class AgentGoalIntegration:
    """Mixin providing the goal-loop hooks for :class:`Agent`.

    Expects the concrete :class:`Agent` to set the following
    attributes (all populated by :meth:`Agent.__init__`):

      * ``self.cfg`` -- the active :class:`~athena.config.Config`
      * ``self.goal_state`` -- the loaded
        :class:`~athena.goal.state.GoalState` or ``None``
      * ``self.stats`` -- :class:`Stats` counter for token bookkeeping
      * ``self._last_turn_interrupted`` -- ``bool``
      * ``self._last_assistant_text`` -- ``str``
      * ``self._goal_loop_tokens_used`` -- ``int`` (the mixin updates
        this every turn the goal loop runs)
      * ``self._profile_dir()`` -- helper returning the profile dir
    """

    # Type-only declarations so mypy (and IDE tooling) understand the
    # attributes the mixin reaches into. The actual values come from
    # ``Agent.__init__`` -- the mixin never assigns to them.
    if TYPE_CHECKING:  # pragma: no cover - typing only
        goal_state: GoalState | None
        _last_turn_interrupted: bool
        _last_assistant_text: str
        _goal_loop_tokens_used: int

    def _consult_goal_continuation(self, *, tokens_at_loop_start: int) -> str | None:
        """T5-07 hook called after each real assistant turn.

        Returns the synthetic prompt to inject for the next
        continuation, or None when the loop should stop. Handles
        the four stop conditions:

          interrupted     Ctrl+C anywhere → pause + return None
          token cap       loop tokens > goal_max_tokens → exhaust
          turn cap        turns_taken >= max_turns → exhausted
          sentinel        GOAL ACHIEVED → achieved
                          GOAL BLOCKED → paused + surface reason

        The returned synthetic prompt is the continuation nudge --
        run_turn will pass it to _run_turn_inner as the next
        "user" message.
        """
        if self.goal_state is None:
            return None

        # Interrupt wins over every continuation decision. A user
        # who hit Ctrl+C does not want another synthetic turn.
        if self._last_turn_interrupted:
            self.goal_state.status = "paused"
            self._persist_goal_state()
            ui.warn("goal paused (interrupt detected) — /goal resume to continue")
            return None

        # Token-cap check. The cap counts tokens consumed since
        # run_turn entered THIS loop (so /goal set + user turn
        # don't pre-consume the budget).
        used_this_loop = (self.stats.prompt_tokens + self.stats.eval_tokens) - tokens_at_loop_start
        self._goal_loop_tokens_used = used_this_loop
        token_cap = int(getattr(self.cfg, "goal_max_tokens", 200_000))
        if token_cap > 0 and used_this_loop > token_cap:
            self.goal_state.status = "exhausted"
            self._persist_goal_state()
            ui.warn(
                f"goal exhausted (token cap {token_cap} exceeded — "
                f"{used_this_loop} used). "
                "/goal resume grants more, /goal status, or /goal clear."
            )
            return None

        from ..goal.loop import maybe_continue_goal_after_turn

        # Snapshot the status BEFORE the goal-loop driver runs.
        # ``maybe_continue_goal_after_turn`` returns ``stop_reason ==
        # state.status`` for any non-active state, meaning a goal that
        # was already terminal (achieved / paused / exhausted) re-fires
        # the same stop_reason on every subsequent turn until the user
        # explicitly clears it. Only announce on the active -> terminal
        # transition so a long Discord conversation post-achievement
        # doesn't print "Goal achieved" after every reply. ``getattr``
        # default covers SimpleNamespace test stubs that don't carry
        # the field.
        pre_status = getattr(self.goal_state, "status", "active")

        decision = maybe_continue_goal_after_turn(
            profile_dir=self._profile_dir(),
            state=self.goal_state,
            last_assistant_text=self._last_assistant_text,
            cfg=self.cfg,
        )
        if decision.should_continue:
            ui.info(
                f"[goal] continuing "
                f"(turn {self.goal_state.turns_taken}/"
                f"{self.goal_state.max_turns})"
            )
            return decision.synthetic_prompt

        # If the loop was already terminal at the start of this call,
        # there is no NEW outcome to surface -- swallow silently and
        # leave the state where it was. The user already saw the
        # announcement the first time.
        if pre_status != "active":
            return None

        # Stop. Announce the reason.
        if decision.stop_reason == "achieved":
            # Distinguish "verified achievement" (verifier ran + passed)
            # from "self-declared achievement" (no verifier configured --
            # model said done, we believed it). This matters because a
            # silent "Goal achieved" with no verifier looks identical to
            # a properly-checked completion, masking the gap.
            verifier_configured = bool(getattr(self.cfg, "goal_verifier_command", None))
            if verifier_configured:
                ui.console.print(
                    f"[bold green]Goal achieved[/] in "
                    f"{self.goal_state.turns_taken} turn(s) "
                    "[dim](verifier passed)[/]"
                )
            else:
                ui.console.print(
                    f"[bold green]Goal achieved[/] in "
                    f"{self.goal_state.turns_taken} turn(s) "
                    "[yellow](self-declared; no verifier configured -- "
                    "set cfg.goal_verifier_command to gate this)[/]"
                )
        elif decision.stop_reason == "blocked":
            ui.warn(f"goal blocked: {decision.blocked_reason}. /goal resume when ready.")
        elif decision.stop_reason == "exhausted":
            ui.warn(
                f"goal not completed after {self.goal_state.max_turns} "
                "turn(s). /goal resume (grants more), /goal status, "
                "or /goal clear."
            )
        # Other stop_reasons (paused, no_state, disabled) are silent --
        # the user either set them themselves (paused) or the loop
        # isn't engaged (no_state, disabled).
        return None

    def _persist_goal_state(self) -> None:
        """Best-effort write of self.goal_state. A disk error is
        logged but never raised -- the loop is already mid-stop."""
        if self.goal_state is None:
            return
        try:
            from ..goal.state import save_state

            save_state(self._profile_dir(), self.goal_state)
        except Exception:  # noqa: BLE001
            logger.debug("could not persist goal state on stop", exc_info=True)
