"""Standard IR and grounding metrics. Relevance is judged at the source (document) level."""

from __future__ import annotations

import math
from collections.abc import Sequence


def dedupe(ranked: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(ranked))


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(dedupe(ranked)[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    top = dedupe(ranked)[:k]
    return len([d for d in top if d in relevant]) / k if k else 0.0


def hit_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return 1.0 if set(dedupe(ranked)[:k]) & relevant else 0.0


def reciprocal_rank(ranked: Sequence[str], relevant: set[str], k: int | None = None) -> float:
    for i, d in enumerate(dedupe(ranked)[:k] if k else dedupe(ranked), start=1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG: DCG = Σ rel_i / log2(i + 1); IDCG from an ideal ordering."""
    top = dedupe(ranked)[:k]
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(top, start=1) if d in relevant)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
