import math

import pytest

from evaluation.metrics import hit_at_k, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank

RANKED = ["a", "x", "b", "a", "y"]  # duplicate "a" must count once
REL = {"a", "b"}


def test_recall_precision_hit():
    assert recall_at_k(RANKED, REL, 1) == 0.5
    assert recall_at_k(RANKED, REL, 3) == 1.0
    assert precision_at_k(RANKED, REL, 2) == 0.5
    assert precision_at_k(RANKED, REL, 4) == 0.5  # deduped list: a, x, b, y
    assert hit_at_k(["x", "y"], REL, 2) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank(["x", "b"], REL) == 0.5
    assert reciprocal_rank(["x", "y"], REL) == 0.0
    assert reciprocal_rank(["x", "y", "a"], REL, k=2) == 0.0


def test_ndcg_matches_hand_computation():
    dcg = 1 / math.log2(2) + 1 / math.log2(4)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(RANKED, REL, 3) == pytest.approx(dcg / idcg)
    assert ndcg_at_k(["a", "b"], REL, 2) == pytest.approx(1.0)
