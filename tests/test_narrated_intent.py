"""detect_narrated_intent — the heuristic behind the narrate-without-act
guard (a turn that ends on 'I'll ...' / 'Let me ...' while making zero
tool calls is narrating instead of acting).
"""

from __future__ import annotations

import pytest

from athena.text_utils import detect_narrated_intent


@pytest.mark.parametrize(
    "text",
    [
        "I'll run the tests now.",
        "Let me check the logs.",
        "Next, I'll update the config and re-run.",
        "I'm going to refactor this function.",
        "Sounds good. I will start by reading the file.",
        "Okay — let me dig into the failing case.",
    ],
)
def test_flags_narrated_intent(text: str) -> None:
    assert detect_narrated_intent(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Done — all 3 tests pass and the fix is committed.",
        "I ran the suite and everything is green.",  # past tense
        "Would you like me to proceed with the refactor?",  # question to user
        "Let me know if you'd like anything else.",  # user-directed
        "I'll wait for your confirmation before deleting.",  # deferring to user
        "I'll need your API key to continue.",  # blocked on user input
        "The bug is in line 42; the off-by-one is clear.",  # plain statement
    ],
)
def test_does_not_flag(text: str) -> None:
    assert detect_narrated_intent(text) is False


def test_only_tail_is_examined() -> None:
    # Mentions intent early, but the message ENDS on a real conclusion —
    # not a stall. Should not flag.
    text = (
        "I'll start by reading the module. "
        + "Here is a long summary of what I found. " * 8
        + "All done: the tests pass and the change is in place."
    )
    assert detect_narrated_intent(text) is False
