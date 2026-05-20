"""Tests for reciprocal-rank fusion (T6-01.1).

RRF is a pure function with one tuning knob (``k``). The tests
pin the documented properties: the fused order reflects summed
1/(k+rank+1) across both lists, and degenerate inputs (empty,
disjoint) behave sanely.
"""

from __future__ import annotations

import pytest

from athena.recall.hybrid import rrf_fuse


# ---------------------------------------------------------------------------
# Core fusion properties
# ---------------------------------------------------------------------------


def test_rrf_fuse_combines_ranks():
    """A doc appearing in both lists should rank above a doc
    that's only in one — that's the whole point of fusion."""
    kw = ["A", "B", "C"]
    vec = ["B", "D", "E"]
    fused = rrf_fuse(kw, vec)
    # B appears in both → score = 1/(60+1) + 1/(60+1) > 1/(60+1)
    assert fused[0] == "B"
    # A and D are each rank-0 in one list, rank-absent in other.
    # B's combined score > A's solo score > others ranked lower.
    assert fused.index("B") < fused.index("A")
    assert fused.index("B") < fused.index("D")


def test_rrf_fuse_handles_disjoint_lists():
    """Two disjoint lists → all docs surface; order follows each
    doc's RRF score across the single list it appears in (top
    ranks in either list win)."""
    kw = ["A", "B", "C"]
    vec = ["X", "Y", "Z"]
    fused = rrf_fuse(kw, vec)
    assert set(fused) == {"A", "B", "C", "X", "Y", "Z"}
    # Rank-0 in either list ties; rank-1 in either ties; etc.
    # A and X both have score 1/(60+1); A appears earlier in
    # iteration so it surfaces first (Python's sort is stable and
    # we iterate kw before vec when building scores).
    assert fused[0] in {"A", "X"}
    # The last two are the rank-2 docs (lowest score).
    assert set(fused[-2:]) == {"C", "Z"}


def test_rrf_fuse_empty_inputs():
    """Both lists empty → empty output, no crash."""
    assert rrf_fuse([], []) == []


def test_rrf_fuse_one_empty_input():
    """One empty list → result is the other list in its
    original order."""
    fused = rrf_fuse([], ["A", "B", "C"])
    assert fused == ["A", "B", "C"]


def test_rrf_fuse_deduplicates_repeats():
    """A doc duplicated within ONE list contributes its rank
    score only — repeat occurrences within the same list add up
    (a downstream artifact of how the algorithm sums). We
    document that here; if a caller wants strict dedup, they
    pre-dedupe."""
    kw = ["A", "A", "B"]
    fused = rrf_fuse(kw, [])
    # Output is unique even though A appeared twice in input.
    assert sorted(fused) == ["A", "B"]


def test_rrf_fuse_k_smooths_decay():
    """Larger k → rank gaps matter less → lists weighed more
    equally. With k=1, rank 0 dominates rank 1. With k=1000, the
    gap is tiny.

    We verify the relative effect: with very large k, a doc in
    both lists at low ranks ranks above a doc at rank 0 in
    only one list. With very small k, rank-0-only doc wins.
    """
    # 'BOTH' is in both lists at rank 9 (low). 'SOLO' is rank 0
    # in keyword only.
    kw = ["SOLO"] + ["filler%d" % i for i in range(8)] + ["BOTH"]
    vec = ["v%d" % i for i in range(9)] + ["BOTH"]
    # k=1: rank-0 SOLO score ~ 1/2; BOTH score ~ 2/11 (both
    # rank-9 → 1/11 each) → SOLO wins.
    fused_small = rrf_fuse(kw, vec, k=1)
    assert fused_small.index("SOLO") < fused_small.index("BOTH")
    # k=1000: SOLO ~ 1/1001; BOTH ~ 2/1010 → BOTH wins.
    fused_large = rrf_fuse(kw, vec, k=1000)
    assert fused_large.index("BOTH") < fused_large.index("SOLO")
