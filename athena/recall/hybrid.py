"""Reciprocal-rank fusion of keyword + vector results (T6-01.1).

Two ranked lists of document IDs come in (one from FTS5 keyword
matching, one from vector cosine search); a single fused order
comes out. RRF is the parameter-light, robust choice: no score
normalisation between the rankers, just a sum of ``1/(k+rank)``
across the lists.

  score(doc) = Σ_lists 1 / (k + rank_in_list + 1)

A doc appearing in both lists scores higher than a doc in either
alone — that's the hybrid win. A doc absent from a list
contributes 0 from that list. ``k`` smooths the rank decay; the
default 60 is what the literature uses and it's been robust in
practice. Larger ``k`` → ranks matter less, lists weighed more
equally; smaller ``k`` → top-ranked docs dominate.

Pure function; no I/O.
"""

from __future__ import annotations


def rrf_fuse(
    keyword_ranked: list[str],
    vector_ranked: list[str],
    *,
    k: int = 60,
) -> list[str]:
    """Fuse two ranked lists of doc IDs via reciprocal-rank
    fusion. Returns the unique fused order, highest score first.

    Each input is the ranker's top results in rank order (best
    first). The lists may overlap, be disjoint, or be empty
    independently. The fused output deduplicates; a doc's final
    rank reflects its summed RRF score across both lists.
    """
    scores: dict[str, float] = {}
    for ranked in (keyword_ranked, vector_ranked):
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return [
        doc_id
        for doc_id, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ]
