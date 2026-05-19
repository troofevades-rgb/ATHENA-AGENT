"""Per-turn review orchestrator. Fires from Agent.run_turn after delivery.

The orchestrator is fire-and-forget: it spawns a daemon thread that runs
``Agent.fork`` and discards the result (or hands it to ``summary.extract``
for status-line display, depending on caller). The foreground turn never
waits on the review.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Any

from . import nudge

if TYPE_CHECKING:
    from ..agent.core import Agent

logger = logging.getLogger(__name__)


def _format_last_messages(messages: list[dict[str, Any]]) -> str:
    """Render the tail of the parent's conversation for review context."""
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def maybe_fire_review(parent_agent: Agent) -> threading.Thread | None:
    """Increment the nudge counter; if it's at an interval boundary, spawn a
    review fork on a daemon thread and return the thread (so tests can join).
    Returns None when the review doesn't fire (counter not at boundary,
    review disabled, session persistence off, or no last-turn context yet)."""
    review_cfg = getattr(parent_agent.cfg, "review", None)
    if review_cfg is None or review_cfg.disabled:
        return None
    if parent_agent.session_id is None:
        return None
    if not nudge.increment_and_check(parent_agent.session_id, review_cfg.nudge_interval):
        return None
    if len(parent_agent.messages) < 2:
        # Nothing meaningful to review yet (just the system message).
        return None

    # Pull the last few messages as context for the review.
    last_messages = parent_agent.messages[-4:]
    history_block = _format_last_messages(last_messages)

    # Build the addendum at fire time (deferred import — keeps the review
    # subpackage import-time cheap and avoids a cycle with prompts.py).
    from . import prompts as review_prompts

    addendum = review_prompts.COMBINED + "\n\n---\n\n## Last-turn context\n" + history_block
    captured_result: dict[str, Any] = {}

    def _runner() -> None:
        from ..agent.fork import fork

        try:
            result = fork(
                parent_agent,
                enabled_toolsets=["memory", "skills"],
                system_addendum=addendum,
                conversation_history=list(last_messages),
                max_iterations=review_cfg.max_iterations,
                write_origin="background_review",
                auxiliary_client=True,
                quiet=True,
            )
            captured_result["result"] = result
            # Surface a structured summary on the parent agent so the TUI (or
            # CLI status helper) can show "Background review: 1 memory entry
            # written" on the next prompt.
            from . import summary as review_summary

            summary_obj = review_summary.extract_summary(result)
            parent_agent.last_review_summary = summary_obj
            if summary_obj["memory_writes"] or summary_obj["skill_changes"]:
                logger.info(
                    "background review: %d memory write(s), %d skill change(s)",
                    len(summary_obj["memory_writes"]),
                    len(summary_obj["skill_changes"]),
                )
        except Exception:
            logger.exception("background review fork failed")

    t = threading.Thread(
        target=_runner,
        daemon=True,
        name=f"review-{parent_agent.session_id[:8]}",
    )
    t.start()
    return t
