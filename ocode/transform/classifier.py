"""Trajectory extraction + auto-classification.

A *trajectory* is a single user request and the assistant work that
answered it: every message from a user turn through the next final
assistant message (one that has no ``tool_calls``). Tool-calling rounds
inside that span are part of the trajectory.

Trajectories are the unit of training-data curation. The auto-classifier
is intentionally conservative — it suggests a label for obvious cases
(``good`` when the next user message is positive, ``bad`` when tool
results show errors that propagated, ``preference_pair`` when a
``/steer`` resulted in recovery) and leaves everything else for human
review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


Label = Literal["good", "bad", "preference_pair", "skip", "unreviewed"]

VALID_LABELS: tuple[Label, ...] = (
    "good", "bad", "preference_pair", "skip", "unreviewed",
)


# Patterns used by the auto-classifier. Kept module-level so tests can
# import and tweak them, and so the regex objects are compiled once.

_ERROR_PREFIX_RE = re.compile(r"^(?:Error:|Traceback|BLOCKED\b|DENIED\b)", re.I)
_TRACEBACK_SIG_RE = re.compile(
    r"Traceback \(most recent call last\):|"
    r"^\s*File \".+?\", line \d+", re.M,
)
_NEGATIVE_OPENERS = (
    "no", "nope", "wrong", "undo", "/undo", "actually",
    "stop", "don't", "do not",
)
_POSITIVE_OPENERS = (
    "thanks", "thank you", "perfect", "great", "nice", "good",
    "awesome", "lgtm", "ship it",
)
_POSITIVE_EMOJIS = ("👍", "🎉", "✅", "💯")
_STEER_TAG_RE = re.compile(r"^\[/steer\]", re.M)


@dataclass
class Trajectory:
    """One user-prompt → final-assistant slice of a session.

    ``turns`` is the slice of the session's message list bounded by
    ``turn_start`` (the user message that opens the trajectory) and
    ``turn_end`` (the final assistant message that closes it).
    ``auto_label`` is the heuristic suggestion; ``user_label`` is what
    the human reviewer assigned (and is the canonical signal for
    dataset construction).
    """
    session_id: str
    turn_start: int
    turn_end: int
    turns: list[dict[str, Any]]
    auto_label: Label = "unreviewed"
    user_label: Label = "unreviewed"
    metadata: dict[str, Any] = field(default_factory=dict)


def extract_trajectories(
    session_id: str,
    messages: list[dict[str, Any]],
) -> list[Trajectory]:
    """Walk ``messages`` and emit a Trajectory per user→final-assistant span.

    A trajectory starts at every ``role == "user"`` message (skipping
    synthetic ``[/steer]`` messages — they continue the prior trajectory
    rather than start a new one) and ends at the next ``role == "assistant"``
    message that has no ``tool_calls``. A user message with no following
    final assistant message is dropped (the turn was interrupted before
    completion).
    """
    out: list[Trajectory] = []
    n = len(messages)
    i = 0
    while i < n:
        msg = messages[i]
        if msg.get("role") != "user":
            i += 1
            continue
        # Skip synthetic /steer messages — they extend the prior turn.
        content = msg.get("content") or ""
        if isinstance(content, str) and content.startswith("[/steer]"):
            i += 1
            continue
        start = i
        # Find the next final assistant message (no tool_calls).
        j = i + 1
        final = -1
        while j < n:
            m = messages[j]
            if m.get("role") == "assistant" and not m.get("tool_calls"):
                final = j
                break
            j += 1
        if final == -1:
            # Unterminated trajectory; skip.
            i += 1
            continue
        slice_ = messages[start: final + 1]
        out.append(Trajectory(
            session_id=session_id,
            turn_start=start,
            turn_end=final,
            turns=list(slice_),
        ))
        i = final + 1
    return out


def auto_classify(
    trajectory: Trajectory,
    *,
    next_user_message: dict[str, Any] | None = None,
) -> Label:
    """Apply conservative heuristics to suggest a label.

    ``next_user_message`` is the user turn that follows ``trajectory``
    (or ``None`` if this is the last trajectory). Positive/negative
    openers in it are strong signals.
    """
    turns = trajectory.turns

    contained_steer = _contains_steer(turns)
    had_error = _had_propagating_error(turns)

    follow_up_label: Label | None = None
    if next_user_message is not None:
        text = (next_user_message.get("content") or "").strip().lower()
        if any(text.startswith(op) for op in _NEGATIVE_OPENERS):
            follow_up_label = "bad"
        elif (
            any(text.startswith(op) for op in _POSITIVE_OPENERS)
            or any(emoji in text for emoji in _POSITIVE_EMOJIS)
        ):
            follow_up_label = "good"

    if contained_steer and _had_recovery_after_steer(turns):
        return "preference_pair"

    if had_error:
        return "bad"

    if follow_up_label == "bad":
        return "bad"

    if follow_up_label == "good":
        return "good"

    return "unreviewed"


# ---- Heuristic helpers --------------------------------------------------


def _had_propagating_error(turns: list[dict[str, Any]]) -> bool:
    """Tool messages flagged as errors that the assistant didn't recover from.

    Recovery is approximated as: a final assistant message exists AND
    the last tool message in the trajectory wasn't an error. So an
    intermediate error followed by a successful tool call + final
    response is *not* counted as bad.
    """
    last_tool_error: bool | None = None
    for m in turns:
        if m.get("role") != "tool":
            continue
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        is_error = bool(
            _ERROR_PREFIX_RE.search(content)
            or _TRACEBACK_SIG_RE.search(content)
        )
        last_tool_error = is_error
    return bool(last_tool_error)


def _contains_steer(turns: list[dict[str, Any]]) -> bool:
    """Trajectory contains a synthetic [/steer] user message somewhere
    in the middle (a steer that landed during execution)."""
    for m in turns[1:]:  # skip the opening user message
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, str) and _STEER_TAG_RE.search(content):
            return True
    return False


def _had_recovery_after_steer(turns: list[dict[str, Any]]) -> bool:
    """After the steer marker, an assistant message lands AND no
    subsequent tool message is an error. Approximation for "the steer
    redirected the work and it finished cleanly"."""
    steer_idx: int | None = None
    for i, m in enumerate(turns):
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, str) and _STEER_TAG_RE.search(content):
            steer_idx = i
            break
    if steer_idx is None:
        return False
    tail = turns[steer_idx + 1:]
    has_final_assistant = any(
        m.get("role") == "assistant" and not m.get("tool_calls")
        for m in tail
    )
    if not has_final_assistant:
        return False
    # Any error in the tail dooms it.
    for m in tail:
        if m.get("role") != "tool":
            continue
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if _ERROR_PREFIX_RE.search(content) or _TRACEBACK_SIG_RE.search(content):
            return False
    return True
