import math

import pytest

from ayumitra_ai.models import HashingEmbedder
from ayumitra_ai.retrieval.bm25 import BM25Index
from ayumitra_ai.retrieval.fusion import reciprocal_rank_fusion
from ayumitra_ai.retrieval.hybrid import HybridRetriever, RetrievalConfig
from ayumitra_ai.retrieval.query import build_queries, deterministic_rewrites, expand_abbreviations, llm_rewrites
from ayumitra_ai.schemas import Domain
from ayumitra_ai.store.vector_store import EmbeddingModelMismatch, VectorStore


class TestBM25:
    def test_score_matches_hand_computation(self):
        idx = BM25Index(k1=1.5, b=0.75).build([("a", "zentrine zentrine level"), ("b", "quorvin level"), ("c", "plinth")])
        hit = idx.search("zentrine", k=3)
        assert [h.chunk_id for h in hit] == ["a"]
        n, df, tf, dl, avgdl = 3, 1, 2, 3, (3 + 2 + 1) / 3
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        expected = idf * tf * 2.5 / (tf + 1.5 * (1 - 0.75 + 0.75 * dl / avgdl))
        assert hit[0].score == pytest.approx(expected)

    def test_idf_never_negative_for_common_terms(self):
        idx = BM25Index().build([(str(i), "level") for i in range(5)])
        assert idx.idf("level") > 0

    def test_allowed_filter_and_no_match(self):
        idx = BM25Index().build([("a", "zentrine"), ("b", "zentrine test")])
        assert [h.chunk_id for h in idx.search("zentrine", allowed={"b"})] == ["b"]
        assert idx.search("nothing-here") == []


class TestRRF:
    def test_formula(self):
        fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60))
        assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
        assert fused["a"] == pytest.approx(1 / 61)
        assert fused["c"] == pytest.approx(1 / 62)

    def test_agreement_beats_single_list_top(self):
        order = [d for d, _ in reciprocal_rank_fusion([["x", "shared"], ["y", "shared"], ["z", "shared"]])]
        assert order[0] == "shared"

    def test_duplicates_in_one_list_count_once_and_weights(self):
        fused = dict(reciprocal_rank_fusion([["a", "a", "b"]], k=60))
        assert fused["a"] == pytest.approx(1 / 61)
        weighted = dict(reciprocal_rank_fusion([["a"], ["b"]], weights=[2.0, 1.0]))
        assert weighted["a"] == pytest.approx(2 * weighted["b"])


class TestQueryRewriting:
    def test_expands_abbreviations(self):
        assert "hemoglobin A1C glycated hemoglobin" in expand_abbreviations("What is HbA1c?")
        assert expand_abbreviations("What about TSH") == "What about TSH (thyroid stimulating hormone)"

    def test_strips_filler_and_keeps_original_first(self):
        qs = deterministic_rewrites("Hi, can you please tell me what LDL means")
        assert qs[0] == "Hi, can you please tell me what LDL means"
        assert any(q.startswith("what LDL") for q in qs)

    def test_llm_failure_gives_no_extra_queries(self):
        class Broken:
            def complete(self, *a, **k):
                raise RuntimeError("down")

        assert llm_rewrites("q", Broken()) == []
        assert build_queries("What is HbA1c?", llm=Broken(), use_llm=True) == deterministic_rewrites("What is HbA1c?")


class TestVectorStore:
    def test_refuses_to_mix_embedding_models(self, tmp_path, embedder):
        from ayumitra_ai.schemas import Chunk

        VectorStore(tmp_path, embedder).upsert([Chunk(id="c1", source_id="s", section_id="s#0", domain=Domain.GENERAL,
                                                      text="t", embed_text="t", heading_path=["T"], order=0, word_count=1)])
        other = HashingEmbedder(dim=256, model_id=embedder.model_id)
        other.dim = 128  # same name, different dimension
        with pytest.raises(EmbeddingModelMismatch):
            VectorStore(tmp_path, other).count(Domain.GENERAL)


class TestHybrid:
    def test_finds_the_right_source_and_records_ranks(self, ingested, embedder):
        from ayumitra_ai.models import LexicalReranker

        db, vectors, _ = ingested
        r = HybridRetriever(db, vectors, embedder, LexicalReranker())
        results, trace = r.retrieve(["What does a high zentrine level mean?"], cfg=RetrievalConfig(rerank_k=3))
        assert results[0].source.id == "test-zentrox"
        assert "42 units" in results[0].chunk.text
        assert results[0].rerank_score is not None
        assert trace.fused and set(trace.timings_ms) == {"dense", "bm25", "fusion", "rerank"}

    def test_domain_and_source_filters(self, ingested, embedder):
        db, vectors, _ = ingested
        r = HybridRetriever(db, vectors, embedder, None)
        results, _ = r.retrieve(["zentrine quorvin"], domains=[Domain.GENERAL])
        assert results and {x.chunk.domain for x in results} == {Domain.GENERAL}
        results, _ = r.retrieve(["zentrine quorvin"], source_ids={"test-zentrox"})
        assert results and {x.source.id for x in results} == {"test-zentrox"}

    @pytest.mark.parametrize("dense,bm25", [(True, False), (False, True)])
    def test_single_retriever_modes(self, ingested, embedder, dense, bm25):
        db, vectors, _ = ingested
        r = HybridRetriever(db, vectors, embedder, None)
        results, trace = r.retrieve(["plinth minerals in urine"], cfg=RetrievalConfig(use_dense=dense, use_bm25=bm25, use_rerank=False))
        assert results[0].source.id == "test-quorvin"
        assert bool(trace.dense) is dense and bool(trace.bm25) is bm25


def test_vitamin_chemical_names_expand_to_vitamin():
    from ayumitra_ai.retrieval.query import deterministic_rewrites

    assert any("vitamin E" in v for v in deterministic_rewrites("TOCOPHEROL"))
    assert any("vitamin B12" in v for v in deterministic_rewrites("What is cobalamin?"))
