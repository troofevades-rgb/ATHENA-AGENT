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


# Policy-refusal phrasings — the model DECLINED the request itself
# ("I can't help with that", "I must decline", "against my guidelines")
# rather than hitting a concrete task limit. Small / quantised local
# models frequently surface-pattern a perfectly legitimate dev task into
# one of these; pairing a match with a zero-tool-call turn lets the agent
# loop offer ONE reframing re-prompt (see runtime.py) before giving up.
#
# HIGH-PRECISION by design: a false negative (a missed refusal) just
# means no nudge; a false positive accuses the model of refusing when it
# was doing legitimate scoped work ("I won't write that migration since
# the schema didn't change") and wastes a round-trip. So refusal verbs
# are limited to help/assist/comply/do-that ANCHORED to the request
# object — generic dev verbs (write/create/generate/provide/support/
# continue/change) are NOT refusal signals on their own. The apostrophe
# class is permissive (curly ’ is normalised in detect_false_refusal).
_REFUSAL = re.compile(
    r"("
    # Refusal of the REQUEST itself: help/assist anchored to that/this/
    # your request/it, or comply / do that. "I can't help with that",
    # "I won't be able to help with this request", "I cannot comply".
    r"\bi (?:can't|cannot|won't|will not|am not able to|'m not able to|"
    r"am unable to|'m unable to) (?:be able to )?"
    r"(?:(?:help|assist) (?:you )?(?:with )?(?:that\b|this\b|your request|"
    r"the request|it\b|here\b)|comply\b|do (?:that|this)\b)"
    r"|\b(?:provide|offer) (?:any )?assistance with\b"
    # Explicit decline / discomfort.
    r"|\bi (?:must|have to|need to|will) (?:respectfully )?(?:decline|refuse)\b"
    r"|\bi'm not (?:comfortable|willing)\b"
    r"|\bi (?:do not|don't) feel comfortable\b"
    # Policy / ethics cue.
    r"|against (?:my |the )?(?:guidelines|policy|policies|principles|"
    r"programming|values)\b"
    # "as an AI … can't/cannot/won't/unable"
    r"|\bas an ai\b[^.!?\n]{0,60}\b(?:can't|cannot|won't|unable|not able)\b"
    # Apologetic refusal: "I'm sorry/afraid … can't/cannot/won't/decline".
    # The capability-exclude below stops "I'm afraid I can't find X" here.
    r"|\b(?:i'm |i am )?(?:sorry|afraid)\b[^.!?\n]{0,40}"
    r"\b(?:can't|cannot|won't|decline|unable|not able)\b"
    r")",
    re.IGNORECASE,
)
# Task-CAPABILITY limitations, NOT policy refusals — the model is willing
# but blocked by a concrete fact ("I can't find the file"). Never treat
# these as refusals: nudging here would just loop on a real blocker. Also
# catches the idiom "can't help but/feeling".
_REFUSAL_EXCLUDE = re.compile(
    r"can't find|couldn't find|can't locate|couldn't locate|"
    r"can't access|don't have access|can't reach|can't connect|"
    r"can't reproduce|can't determine|can't see|can't read|"
    r"unable to find|unable to locate|unable to access|unable to read|"
    r"can't open|no such file|does not exist|doesn't exist|"
    r"can't help but|can't help feeling|cannot help but",
    re.IGNORECASE,
)


def detect_false_refusal(text: str) -> bool:
    """True when ``text`` looks like a POLICY refusal of the request
    (the model declined to help) rather than a concrete task-capability
    limitation ("I can't find the file").

    Consult ONLY for a zero-tool-call turn — a refusal that produced no
    action. This drives a single, bounded reframing re-prompt for the
    common small/local-model failure of spuriously refusing legitimate
    development work; it is NOT a judgment that the request is safe, and
    the model can still decline after the nudge. Conservative: a real
    task blocker ("can't find X") or the idiom "can't help but" never
    triggers it, and a reply that ends on a question to the user (not a
    refusal) is skipped.
    """
    if not text:
        return False
    # Normalise curly quotes so smart-apostrophe output (which many
    # models emit) doesn't slip every contraction past the patterns.
    t = text.strip().replace("’", "'").replace("‘", "'")
    if not t:
        return False
    # A reply that ends on a question is addressed to the user, not a
    # refusal ("I can't tell which file — which one did you mean?").
    if t.rstrip().endswith("?"):
        return False
    if _REFUSAL_EXCLUDE.search(t):
        return False
    return bool(_REFUSAL.search(t))
