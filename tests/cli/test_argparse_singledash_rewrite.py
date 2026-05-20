"""``-foo`` -> ``--foo`` rewrite + close-match suggestion (T2-08).

The user-on-VPS typo ``athena -model anthropic/claude-sonnet-latest``
silently became ``-m odel anthropic/...`` under default argparse
behaviour. The rewrite preprocesses argv so a known long-form like
``-model`` becomes ``--model``; an unknown typo like ``-modle``
triggers a ``did you mean`` hint on stderr.
"""

from __future__ import annotations

import argparse

import pytest

from athena.__main__ import _rewrite_singledash_longs


@pytest.fixture
def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--model")
    ap.add_argument("-p", "--prompt")
    ap.add_argument("--profile")
    ap.add_argument("--auto-approve", action="store_true")
    ap.add_argument("--lean-prompt", action="store_true")
    return ap


def test_known_long_form_with_singledash_is_rewritten(
    parser: argparse.ArgumentParser,
) -> None:
    out = _rewrite_singledash_longs(["athena", "-model", "qwen2.5-coder:14b"], parser)
    assert out == ["athena", "--model", "qwen2.5-coder:14b"]


def test_double_dash_long_form_is_left_alone(parser: argparse.ArgumentParser) -> None:
    out = _rewrite_singledash_longs(["athena", "--model", "x"], parser)
    assert out == ["athena", "--model", "x"]


def test_known_short_form_is_left_alone(parser: argparse.ArgumentParser) -> None:
    """`-m` must not be rewritten to `--m` (which isn't a flag) just
    because `-m` collides with the long-form check's length filter."""
    out = _rewrite_singledash_longs(["athena", "-m", "foo"], parser)
    assert out == ["athena", "-m", "foo"]


def test_typo_suggests_close_match(
    parser: argparse.ArgumentParser, capsys: pytest.CaptureFixture[str]
) -> None:
    """`-modle` (no such flag, close to `-model`) prints a hint to
    stderr but leaves argv alone so argparse still surfaces the
    error."""
    out = _rewrite_singledash_longs(["athena", "-modle", "foo"], parser)
    # argv unchanged; argparse will then complain.
    assert out == ["athena", "-modle", "foo"]
    captured = capsys.readouterr()
    assert "did you mean --model" in captured.err


def test_unrelated_singledash_token_is_left_alone(
    parser: argparse.ArgumentParser,
) -> None:
    """A single-dash token that isn't close to any long-form passes
    through silently — argparse will error if it's invalid; we don't
    spam stderr."""
    out = _rewrite_singledash_longs(["athena", "-xyzqqq", "foo"], parser)
    assert out == ["athena", "-xyzqqq", "foo"]


def test_equals_separator_handled(parser: argparse.ArgumentParser) -> None:
    """`-model=foo` (single-dash + equals) rewrites to `--model=foo`."""
    out = _rewrite_singledash_longs(["athena", "-model=foo"], parser)
    assert out == ["athena", "--model=foo"]


def test_singledash_hyphenated_long_form(parser: argparse.ArgumentParser) -> None:
    """`-auto-approve` rewrites to `--auto-approve` (hyphen-containing
    long forms work)."""
    out = _rewrite_singledash_longs(["athena", "-auto-approve"], parser)
    assert out == ["athena", "--auto-approve"]
