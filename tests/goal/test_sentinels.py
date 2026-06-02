"""Tests for the GOAL ACHIEVED / GOAL BLOCKED sentinel scanner (T5-07.3).

The scanner is the contract between the model's free-form text
output and the deterministic continuation loop. False positives
(thinking the goal is done when it isn't) are worse than false
negatives — over-eager achievement detection would silently
stop the loop. Tests pin the exact shapes that count and the
shapes that don't.
"""

from __future__ import annotations

import pytest

from athena.goal.loop import scan_sentinels

# ---------------------------------------------------------------------------
# ACHIEVED — positive cases
# ---------------------------------------------------------------------------


def test_sentinel_achieved_plain():
    achieved, reason = scan_sentinels("All tests pass.\nGOAL ACHIEVED")
    assert achieved is True
    assert reason is None


def test_sentinel_achieved_lowercase():
    """Case-insensitive — "goal achieved" still counts."""
    achieved, _ = scan_sentinels("done.\ngoal achieved")
    assert achieved is True


def test_sentinel_achieved_markdown_heading():
    """Markdown ## heading lead-in is tolerated."""
    achieved, _ = scan_sentinels("# Wrapping up\n\n## GOAL ACHIEVED")
    assert achieved is True


def test_sentinel_achieved_blockquote_does_NOT_match():
    """``>`` blockquote lead-in is explicitly EXCLUDED so a model
    quoting the contract back at the user
    (``> GOAL ACHIEVED - when you see this line, stop``) doesn't
    end the loop spuriously. Real model achievements emit the
    sentinel without a quote prefix."""
    achieved, _ = scan_sentinels("> GOAL ACHIEVED")
    assert achieved is False
    achieved, _ = scan_sentinels("> GOAL ACHIEVED - when you see this line, stop")
    assert achieved is False


def test_sentinel_achieved_bullet():
    """A list-marker prefix is tolerated."""
    achieved, _ = scan_sentinels("- GOAL ACHIEVED")
    assert achieved is True


def test_sentinel_achieved_with_trailing_text_same_line():
    """End-of-line slop after the sentinel is allowed — the
    model might append a smiley or period."""
    achieved, _ = scan_sentinels("GOAL ACHIEVED.")
    assert achieved is True


# ---------------------------------------------------------------------------
# ACHIEVED — negative cases
# ---------------------------------------------------------------------------


def test_sentinel_no_match_partial():
    """A line that mentions the words but isn't the sentinel
    pattern doesn't trigger achievement."""
    achieved, _ = scan_sentinels("our goal: achieved next sprint")
    assert achieved is False


def test_sentinel_no_match_when_quoted_in_middle_of_line():
    """ "...the goal achieved earlier was..." mid-sentence isn't
    the sentinel — the regex anchors to a line start."""
    achieved, _ = scan_sentinels("Note the goal achieved earlier was different from this one.")
    assert achieved is False


def test_sentinel_no_sentinel():
    achieved, reason = scan_sentinels("still working on it...")
    assert achieved is False
    assert reason is None


# ---------------------------------------------------------------------------
# BLOCKED — reason extraction
# ---------------------------------------------------------------------------


def test_sentinel_blocked_extracts_reason():
    achieved, reason = scan_sentinels("GOAL BLOCKED: need API key")
    assert achieved is False
    assert reason == "need API key"


def test_sentinel_blocked_strips_whitespace_in_reason():
    _, reason = scan_sentinels("GOAL BLOCKED:    spaces around me   ")
    assert reason == "spaces around me"


def test_sentinel_blocked_lowercase():
    _, reason = scan_sentinels("goal blocked: lowercase too")
    assert reason == "lowercase too"


def test_sentinel_blocked_blockquote_does_NOT_match():
    """Same exclusion as ACHIEVED -- a blockquoted ``> GOAL BLOCKED:``
    is the model quoting the contract, not actually claiming
    blocked."""
    achieved, reason = scan_sentinels("> GOAL BLOCKED: with blockquote")
    assert achieved is False
    assert reason is None


def test_sentinel_blocked_markdown_bullet_lead():
    """A list-marker prefix (``*``, ``-``, ``#``) IS still tolerated
    -- those are real markdown renderings of the sentinel, unlike
    ``>`` which signals quotation."""
    _, reason = scan_sentinels("* GOAL BLOCKED: with bullet")
    assert reason == "with bullet"


def test_sentinel_blocked_empty_reason_normalises_to_none():
    """``GOAL BLOCKED:`` with no reason text → blocked_reason is
    None (the line still doesn't match, since the regex requires
    at least one char after the colon)."""
    achieved, reason = scan_sentinels("GOAL BLOCKED:")
    assert achieved is False
    assert reason is None


# ---------------------------------------------------------------------------
# ACHIEVED beats BLOCKED when both appear
# ---------------------------------------------------------------------------


def test_achieved_wins_over_blocked_when_both_present():
    """If the model emitted both lines (it changed its mind),
    achievement is the commit — the loop honours "done"."""
    achieved, reason = scan_sentinels(
        "GOAL BLOCKED: hit a snag\n...then I fixed it.\nGOAL ACHIEVED"
    )
    assert achieved is True
    assert reason is None


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------


def test_sentinel_empty_string():
    assert scan_sentinels("") == (False, None)


def test_sentinel_non_string():
    """A non-string slipping in (None from a degenerate stream)
    doesn't crash."""
    assert scan_sentinels(None) == (False, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# /steer + /goal interaction (dogfood, the bug that drove this regex rewrite)
# ---------------------------------------------------------------------------


def test_sentinel_achieved_with_steer_suffix_on_separate_line():
    """The exact case from the 2026-05-31 dogfood: an active /steer
    nudged the model to end every reply with the word "DONE". When
    the model completed the goal it emitted ``GOAL ACHIEVED`` then
    a blank line then ``DONE``. The previous last-non-empty-line
    anchor saw ``DONE`` and missed the sentinel, so the loop kept
    firing for half a dozen turns until the operator killed it
    manually. The new multiline regex matches the sentinel
    regardless of what follows it."""
    text = "Files listed.\n\nGOAL ACHIEVED\n\nDONE"
    achieved, _ = scan_sentinels(text)
    assert achieved is True


def test_sentinel_achieved_with_multiple_trailing_lines():
    """More general form of the steer case: any non-quote content
    after the sentinel is fine. The model emitted GOAL ACHIEVED in
    the middle of a longer wrap-up message."""
    text = (
        "Here's the summary:\n"
        "- file a\n"
        "- file b\n"
        "GOAL ACHIEVED\n"
        "Let me know if you want me to do anything else."
    )
    achieved, _ = scan_sentinels(text)
    assert achieved is True


def test_sentinel_blocked_followed_by_steer_suffix():
    """Same interaction for BLOCKED: the model can claim blocked
    even when /steer is appending a suffix."""
    text = "Tried multiple paths.\n\nGOAL BLOCKED: missing API key\n\nDONE"
    achieved, reason = scan_sentinels(text)
    assert achieved is False
    assert reason == "missing API key"
