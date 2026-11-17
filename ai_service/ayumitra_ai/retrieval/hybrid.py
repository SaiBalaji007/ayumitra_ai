"""
Hybrid retrieval: for every query variant, run dense (ChromaDB) and BM25 search, fuse all ranked
lists with RRF, apply metadata filters, then rerank the fused candidates with a cross-encoder.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..models import Embedder, Reranker
from ..schemas import Domain, RetrievedChunk
from ..store.knowledge_db import KnowledgeDB
from ..store.vector_store import VectorStore
from .bm25 import BM25Index
from .fusion import reciprocal_rank_fusion


@dataclass
class RetrievalConfig:
    dense_k: int = 30
    bm25_k: int = 30
    rrf_k: int = 60
    fused_k: int = 25
    rerank_k: int = 6
    use_dense: bool = True
    use_bm25: bool = True
    use_rerank: bool = True


@dataclass
class RetrievalTrace:
    queries: list[str] = field(default_factory=list)
    dense: dict[str, list[str]] = field(default_factory=dict)
    bm25: dict[str, list[str]] = field(default_factory=dict)
    fused: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


class HybridRetriever:
    def __init__(self, db: KnowledgeDB, vectors: VectorStore, embedder: Embedder, reranker: Reranker | None):
        self.db, self.vectors, self.embedder, self.reranker = db, vectors, embedder, reranker
        self._bm25: dict[Domain, BM25Index] = {}
        self._source_cache: dict = {}

    # BM25 indexes are rebuilt from the knowledge DB (cheap at this corpus size).
    def refresh(self) -> None:
        self._bm25.clear()
        self._source_cache.clear()

    def _bm25_for(self, domain: Domain) -> BM25Index:
        if domain not in self._bm25:
            chunks = self.db.chunks(domain)
            self._bm25[domain] = BM25Index().build([(c.id, c.embed_text) for c in chunks])
        return self._bm25[domain]

    def _source(self, source_id: str):
        if source_id not in self._source_cache:
            self._source_cache[source_id] = self.db.get_source(source_id)
        return self._source_cache[source_id]

    def retrieve(
        self,
        queries: list[str],
        *,
        domains: list[Domain] | None = None,
        source_ids: set[str] | None = None,
        cfg: RetrievalConfig | None = None,
        rerank_query: str | None = None,
    ) -> tuple[list[RetrievedChunk], RetrievalTrace]:
        cfg = cfg or RetrievalConfig()
        domains = domains or list(Domain)
        trace = RetrievalTrace(queries=list(queries))
        where = {"source_id": {"$in": sorted(source_ids)}} if source_ids else None
        allowed_ids = None
        if source_ids:
            allowed_ids = {c.id for d in domains for c in self.db.chunks(d) if c.source_id in source_ids}

        rankings: list[list[str]] = []
        dense_rank: dict[str, int] = {}
        bm25_rank: dict[str, int] = {}
        matched: dict[str, set[str]] = {}

        t0 = time.perf_counter()
        if cfg.use_dense:
            qvecs = self.embedder.embed_queries(queries)
            for q, vec in zip(queries, qvecs, strict=True):
                ids = [h.chunk_id for h in self.vectors.search(vec, domains, cfg.dense_k, where)]
                trace.dense[q] = ids
                rankings.append(ids)
                for r, cid in enumerate(ids, 1):
                    dense_rank[cid] = min(r, dense_rank.get(cid, r))
                    matched.setdefault(cid, set()).add(q)
        t1 = time.perf_counter()
        if cfg.use_bm25:
            for q in queries:
                hits = []
                for d in domains:
                    hits.extend(self._bm25_for(d).search(q, cfg.bm25_k, allowed_ids))
                hits.sort(key=lambda h: h.score, reverse=True)
                ids = [h.chunk_id for h in hits[: cfg.bm25_k]]
                trace.bm25[q] = ids
                rankings.append(ids)
                for r, cid in enumerate(ids, 1):
                    bm25_rank[cid] = min(r, bm25_rank.get(cid, r))
                    matched.setdefault(cid, set()).add(q)
        t2 = time.perf_counter()

        fused = reciprocal_rank_fusion(rankings, k=cfg.rrf_k)[: cfg.fused_k]
        trace.fused = [cid for cid, _ in fused]
        chunks = self.db.chunks_by_id(trace.fused)
        results = []
        for cid, score in fused:
            ch = chunks.get(cid)
            if ch is None or ch.domain not in domains:  # metadata filter (defence in depth)
                continue
            if source_ids and ch.source_id not in source_ids:
                continue
            results.append(
                RetrievedChunk(
                    chunk=ch, source=self._source(ch.source_id), dense_rank=dense_rank.get(cid),
                    bm25_rank=bm25_rank.get(cid), fused_score=score, matched_queries=sorted(matched.get(cid, [])),
                )
            )
        t3 = time.perf_counter()

        if cfg.use_rerank and self.reranker is not None and results:
            q = rerank_query or queries[0]
            scores = self.reranker.score(q, [r.chunk.embed_text for r in results])
            for r, s in zip(results, scores, strict=True):
                r.rerank_score = s
            results.sort(key=lambda r: r.rerank_score, reverse=True)
            results = results[: cfg.rerank_k]
        else:
            results = results[: cfg.rerank_k]
        t4 = time.perf_counter()

        trace.timings_ms = {
            "dense": round((t1 - t0) * 1000, 1), "bm25": round((t2 - t1) * 1000, 1),
            "fusion": round((t3 - t2) * 1000, 1), "rerank": round((t4 - t3) * 1000, 1),
        }
        return results, trace
