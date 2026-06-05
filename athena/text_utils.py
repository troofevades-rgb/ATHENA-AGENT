"""Dependency-light text helpers shared across surfaces.

This module deliberately imports nothing beyond the stdlib so it is
safe to use from the server-side gateway (where pulling in ``ui.py``
would drag in Rich and reconfigure stdout) as well as from the
terminal UI.
"""

from __future__ import annotations

import re

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", flags=re.DOTALL)
_THINK_CONTENT = re.compile(r"<think>(.*?)</think>", flags=re.DOTALL)
_OPEN_THINK = "<think>"
_CLOSE_THINK = "</think>"


def strip_think_blocks(
    text: str,
    *,
    closed_replacement: str = "",
    open_replacement: str = "",
) -> str:
    """Remove ``<think>...</think>`` chain-of-thought from ``text``.

    Closed blocks are replaced with ``closed_replacement``. A trailing
    *unclosed* ``<think>`` (the model was cut off mid-thought, common on
    interrupt) is truncated at the opener and replaced with
    ``open_replacement``.

    Defaults strip the thinking out entirely (both replacements empty),
    which is what a chat transport wants. The terminal renderer passes
    non-empty markers so the reader can see a thought happened.
    """
    out = _THINK_BLOCK.sub(closed_replacement, text)
    idx = out.find(_OPEN_THINK)
    if idx != -1:
        out = out[:idx] + open_replacement
    return out


def extract_think_content(text: str) -> str:
    """Return the reasoning hidden inside ``<think>...</think>`` blocks.

    The inverse of :func:`strip_think_blocks`: where that drops the
    chain-of-thought, this collects it. Closed blocks contribute their
    body; a trailing *unclosed* ``<think>`` (model cut off mid-thought)
    contributes whatever followed the opener. Blocks are joined by a
    blank line, each stripped of surrounding whitespace. Returns ``""``
    when there is no thinking — callers treat that as "no reasoning to
    show".

    Used to surface reasoning in the TUI when the reader toggles
    "show reasoning" on; the wire still carries the clean answer in
    ``final_text`` and the raw reasoning separately so the display side
    decides whether to render it.
    """
    blocks = [m.strip() for m in _THINK_CONTENT.findall(text)]
    # A trailing <think> with no matching </think> after it: the model
    # was interrupted mid-thought. Capture the partial body.
    open_idx = text.rfind(_OPEN_THINK)
    if open_idx != -1 and text.rfind(_CLOSE_THINK) < open_idx:
        tail = text[open_idx + len(_OPEN_THINK) :].strip()
        if tail:
            blocks.append(tail)
    return "\n\n".join(b for b in blocks if b)


# First-person, future-tense "I'm about to act" lead-ins. The model's
# own system prompt says "drive tools to completion, not to narrate";
# a turn that ENDS on one of these while making zero tool calls is
# narrating intent instead of taking it.
_NARRATION_INTENT = re.compile(
    r"\b("
    r"i'?ll|i will|i'?m going to|i am going to|i'?m about to|"
    r"let me|let's|let us|next,?\s+i|i'?ll go ahead|i'?ll now"
    r")\b",
    re.IGNORECASE,
)
# Look-alikes that are user-directed or terminal, NOT a deferred
# self-action — don't flag these.
_NARRATION_EXCLUDE = re.compile(
    r"let me know|i'?ll wait|i'?ll need (?:you|your)|if you'?d like|"
    r"would you like|let me explain|i'?ll leave (?:it|that|this) (?:to|for) you",
    re.IGNORECASE,
)


def detect_narrated_intent(text: str) -> bool:
    """True when ``text`` ends on a first-person future-tense intent —
    "I'll run the tests", "Let me check the logs" — i.e. the model
    described a next action rather than taking it.

    Caller should consult this ONLY for a turn that made zero tool
    calls; pairing the two is what distinguishes "narrated and stalled"
    from a normal closing summary after real work. Conservative by
    design (a non-blocking warning, not a re-prompt): only the tail
    (closing sentence or two) is examined, questions to the user are
    ignored, and user-directed look-alikes are excluded.
    """
    if not text:
        return False
    tail = text.strip()[-200:]
    if not tail:
        return False
    # A trailing question is addressed to the user, not a narrated
    # self-action ("Would you like me to proceed?").
    if tail.rstrip().endswith("?"):
        return False
    if _NARRATION_EXCLUDE.search(tail):
        return False
    return bool(_NARRATION_INTENT.search(tail))
