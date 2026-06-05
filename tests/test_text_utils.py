"""Tests for the dependency-light text helpers in ``athena.text_utils``.

Focus here is :func:`extract_think_content` — the inverse of
:func:`strip_think_blocks`, used to surface model reasoning in the TUI
when the reader toggles "show reasoning" (Ctrl+O) on. The two must
agree on what counts as a ``<think>`` block.
"""

from __future__ import annotations

from athena.text_utils import extract_think_content, strip_think_blocks


def test_extract_single_closed_block() -> None:
    text = "<think>weigh the options</think>The answer is 42."
    assert extract_think_content(text) == "weigh the options"


def test_extract_multiple_blocks_joined() -> None:
    text = "<think>first</think>visible<think>second</think>done"
    assert extract_think_content(text) == "first\n\nsecond"


def test_extract_unclosed_trailing_block() -> None:
    # Model cut off mid-thought (common on interrupt): no closing tag.
    text = "before <think>still reasoning, not finished"
    assert extract_think_content(text) == "still reasoning, not finished"


def test_extract_closed_then_unclosed() -> None:
    text = "<think>done thought</think>answer<think>new partial"
    assert extract_think_content(text) == "done thought\n\nnew partial"


def test_no_thinking_returns_empty() -> None:
    assert extract_think_content("just a plain answer") == ""
    assert extract_think_content("") == ""


def test_extract_strips_surrounding_whitespace() -> None:
    text = "<think>\n  padded thought  \n</think>x"
    assert extract_think_content(text) == "padded thought"


def test_inverse_of_strip_on_clean_text() -> None:
    # What strip removes is what extract keeps: between them they
    # partition the model output into answer + reasoning.
    text = "<think>the why</think>the answer"
    assert strip_think_blocks(text) == "the answer"
    assert extract_think_content(text) == "the why"
