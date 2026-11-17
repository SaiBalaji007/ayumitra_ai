"""Okapi BM25 over knowledge chunks, using the medical-aware tokenizer in text.py."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ..text import tokenize


@dataclass
class BM25Hit:
    chunk_id: str
    score: float


class BM25Index:
    """score(q, d) = Σ_t IDF(t) · tf(t,d)·(k1+1) / (tf(t,d) + k1·(1 − b + b·|d|/avgdl))
    with IDF(t) = ln(1 + (N − df + 0.5)/(df + 0.5)), which is never negative."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids: list[str] = []
        self._tf: list[Counter] = []
        self._len: list[int] = []
        self._df: Counter = Counter()
        self._postings: dict[str, list[int]] = {}
        self.avgdl = 0.0

    def build(self, docs: list[tuple[str, str]]) -> BM25Index:
        """docs: (chunk_id, text) pairs."""
        self.__init__(self.k1, self.b)
        for idx, (cid, text) in enumerate(docs):
            tf = Counter(tokenize(text))
            self.ids.append(cid)
            self._tf.append(tf)
            self._len.append(sum(tf.values()))
            for term in tf:
                self._df[term] += 1
                self._postings.setdefault(term, []).append(idx)
        self.avgdl = (sum(self._len) / len(self._len)) if self._len else 0.0
        return self

    def __len__(self) -> int:
        return len(self.ids)

    def idf(self, term: str) -> float:
        n, df = len(self.ids), self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 10, allowed: set[str] | None = None) -> list[BM25Hit]:
        if not self.ids:
            return []
        q_terms = Counter(tokenize(query))
        scores: dict[int, float] = {}
        for term, qtf in q_terms.items():
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            for idx in postings:
                tf = self._tf[idx][term]
                denom = tf + self.k1 * (1 - self.b + self.b * self._len[idx] / self.avgdl)
                scores[idx] = scores.get(idx, 0.0) + qtf * idf * tf * (self.k1 + 1) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        out = []
        for idx, score in ranked:
            cid = self.ids[idx]
            if allowed is not None and cid not in allowed:
                continue
            out.append(BM25Hit(cid, score))
            if len(out) >= k:
                break
        return out
