"""detect_false_refusal — the heuristic behind the false-refusal
recovery (a zero-tool-call turn whose reply is a POLICY refusal of the
request, not a concrete task blocker, gets one reframing re-prompt).
"""

from __future__ import annotations

import pytest

from athena.text_utils import detect_false_refusal


@pytest.mark.parametrize(
    "text",
    [
        "I can't help with that.",
        "I'm sorry, but I cannot assist with creating that bot.",
        "I won't be able to help with this request.",
        "I must respectfully decline.",
        "I'm not comfortable writing that code.",
        "That goes against my guidelines.",
        "I cannot provide assistance with this.",
        "As an AI, I can't help you build that.",
        "I'm afraid I can't continue with this task.",
        "Sorry, I cannot generate that for you.",
        "I do not feel comfortable helping with this.",
        # Curly/smart apostrophe (U+2019) — many models emit it; must
        # not slip past the contraction patterns.
        "I can’t help with that.",
        "I’m not comfortable assisting with this.",
        "I’m sorry, but I can’t do that.",
    ],
)
def test_flags_policy_refusal(text: str) -> None:
    assert detect_false_refusal(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Done — the bot now connects and the webhook works.",
        # Concrete task-capability limitations — NOT policy refusals.
        "I can't find the config file at that path.",
        "I couldn't locate the handler you mentioned.",
        "I can't access that URL from here.",
        "I can't reproduce the crash with the steps given.",
        "I can't read the file — it doesn't exist.",
        "I can't connect to the database; the host is unreachable.",
        "I can't determine the root cause without the stack trace.",
        # Normal helpful prose that isn't a refusal.
        "Here's the fix; I updated the message handler.",
        "The off-by-one is on line 42.",
        # Scoped dev decisions / caveats — NOT policy refusals. These are
        # the false positives the high-precision patterns must avoid.
        "I won't write a migration since the schema didn't change.",
        "I can't provide an exact benchmark, but it should be ~2x faster.",
        "I am not able to provide a 100% accurate estimate.",
        "I won't change the public API without asking you first.",
        "I won't support IE11 here; it's out of scope.",
        "I won't continue down this path; it would break the tests.",
        "I can't write that test until we know the expected output.",
        # "can't help but" idiom — not a refusal.
        "I can't help but notice this design is fragile.",
        # A clarifying question to the user is not a refusal.
        "I can't tell which file you mean — which one did you want?",
    ],
)
def test_does_not_flag(text: str) -> None:
    assert detect_false_refusal(text) is False


def test_capability_phrase_suppresses_a_co_occurring_refusal_word() -> None:
    """Conservative: if a real blocker phrase is present we do NOT nudge,
    even if a refusal-ish word also appears — better to under-trigger
    than loop on a genuine 'can't find X'."""
    assert (
        detect_false_refusal("I can't help until I can't find the missing module file.")
        is False
    )
