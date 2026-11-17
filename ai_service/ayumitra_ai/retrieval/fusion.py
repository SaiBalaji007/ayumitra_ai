"""Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009)."""

from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60, weights: Sequence[float] | None = None) -> list[tuple[str, float]]:
    """Fuse ranked id lists: score(d) = Σ_i w_i / (k + rank_i(d)), with 1-based ranks.

    Only ranks are used, so dense cosine scores and BM25 scores never need calibrating against
    each other. Ties are broken by first appearance, which keeps the output deterministic.
    """
    weights = weights or [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("weights must match rankings")
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for ranking, w in zip(rankings, weights, strict=True):
        seen_here = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id in seen_here:  # duplicates within one list count once, at their best rank
                continue
            seen_here.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
            if doc_id not in first_seen:
                first_seen[doc_id] = order
                order += 1
    return sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))
