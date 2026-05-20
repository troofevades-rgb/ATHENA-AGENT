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


def test_sentinel_achieved_blockquote():
    """> blockquote lead-in is tolerated."""
    achieved, _ = scan_sentinels("> GOAL ACHIEVED")
    assert achieved is True


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
    """"...the goal achieved earlier was..." mid-sentence isn't
    the sentinel — the regex anchors to a line start."""
    achieved, _ = scan_sentinels(
        "Note the goal achieved earlier was different from this one."
    )
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


def test_sentinel_blocked_markdown_lead():
    _, reason = scan_sentinels("> GOAL BLOCKED: with blockquote")
    assert reason == "with blockquote"


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
