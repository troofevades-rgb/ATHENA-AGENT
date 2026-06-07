"""Fuzzy substring matching for ``str_replace`` fallback.

Returns ALL near-matches above the threshold (not just the best).
Multiple matches = the caller MUST error out rather than guess
which one was intended — that's the safety contract that prevents
silent wrong-substring substitution.

Verbatim substring matches short-circuit the fuzzy search: if
``needle`` appears verbatim, every verbatim occurrence is returned
with score 1.0 and the fuzzy scorer is never consulted.

Backend: rapidfuzz if installed (fast C), difflib.SequenceMatcher
otherwise (stdlib, slower). rapidfuzz is NOT a hard dependency —
both paths are tested.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable


@dataclasses.dataclass
class FuzzyMatch:
    start: int
    end: int  # exclusive
    score: float  # 0.0 to 1.0
    matched_text: str


def find_fuzzy_matches(
    haystack: str,
    needle: str,
    *,
    threshold: float = 0.95,
) -> list[FuzzyMatch]:
    """Return ALL substrings of ``haystack`` with similarity ratio
    ``>= threshold`` to ``needle``.

    - Empty needle -> [].
    - Needle longer than haystack -> [].
    - Verbatim substring(s) -> [FuzzyMatch(score=1.0, ...), ...]
      for every occurrence; the fuzzy scorer is skipped.
    - Otherwise: sliding window of len(needle) with a stride of
      max(1, needle_len // 4). On a hit, advance past the match
      by max(stride, needle_len // 2) to avoid heavily-overlapping
      reports.
    """
    if not needle:
        return []
    if len(needle) > len(haystack):
        return []

    # Verbatim short-circuit: scan for every occurrence and return.
    if needle in haystack:
        verbatim_matches: list[FuzzyMatch] = []
        start = 0
        while True:
            idx = haystack.find(needle, start)
            if idx < 0:
                break
            verbatim_matches.append(
                FuzzyMatch(
                    start=idx,
                    end=idx + len(needle),
                    score=1.0,
                    matched_text=needle,
                )
            )
            start = idx + 1
        return verbatim_matches

    scorer = _build_scorer()
    matches: list[FuzzyMatch] = []
    needle_len = len(needle)
    stride = max(1, needle_len // 4)

    i = 0
    while i + needle_len <= len(haystack):
        window = haystack[i : i + needle_len]
        score = scorer(window, needle)
        if score >= threshold:
            matches.append(
                FuzzyMatch(
                    start=i,
                    end=i + needle_len,
                    score=score,
                    matched_text=window,
                )
            )
            # Advance past the match so we don't double-report
            # heavily-overlapping windows.
            i += max(stride, needle_len // 2)
        else:
            i += stride

    return matches


def _build_scorer() -> Callable[[str, str], float]:
    """Return a (a, b) -> float scorer in [0.0, 1.0].

    Prefers rapidfuzz if installed (fast C); falls back to stdlib
    difflib.SequenceMatcher. The choice is made once per call —
    the import cost is negligible relative to the sliding-window
    sweep.
    """
    try:
        from rapidfuzz.fuzz import ratio  # type: ignore[import-not-found]

        def _scorer(a: str, b: str) -> float:
            return float(ratio(a, b)) / 100.0

        return _scorer
    except ImportError:
        from difflib import SequenceMatcher

        def _scorer_difflib(a: str, b: str) -> float:
            return SequenceMatcher(None, a, b).ratio()

        return _scorer_difflib
