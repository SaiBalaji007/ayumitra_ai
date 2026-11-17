"""
RAG evaluation.

  python -m evaluation.run_eval                     retrieval ablation (no LLM needed)
  python -m evaluation.run_eval --generation        + full pipeline: citation accuracy, faithfulness,
                                                      abstention, latency (needs the LLM server)

Dataset: evaluation/datasets/medical_qa.jsonl, one JSON object per line:
  {"id": "...", "question": "...", "relevant_sources": ["mlp-lab-..."], "type": "in_scope" | "out_of_scope"}
Relevance is judged at source level: which trusted page answers the question.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ayumitra_ai.config import SERVICE_ROOT
from ayumitra_ai.pipeline import RagPipeline
from ayumitra_ai.retrieval.query import build_queries

from .metrics import hit_at_k, mean, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank

DATASET = SERVICE_ROOT / "evaluation" / "datasets" / "medical_qa.jsonl"
REPORTS = SERVICE_ROOT / "evaluation" / "reports"


@dataclass
class Variant:
    name: str
    dense: bool
    bm25: bool
    multi_query: bool
    rerank: bool


VARIANTS = [
    Variant("dense only", True, False, False, False),
    Variant("BM25 only", False, True, False, False),
    Variant("hybrid (RRF)", True, True, False, False),
    Variant("hybrid + multi-query", True, True, True, False),
    Variant("hybrid + multi-query + rerank", True, True, True, True),
]


def load_dataset(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def eval_retrieval(p: RagPipeline, items: list[dict]) -> dict:
    in_scope = [it for it in items if it["type"] == "in_scope"]
    table = {}
    for v in VARIANTS:
        rows, latencies = [], []
        for it in in_scope:
            queries = build_queries(it["question"]) if v.multi_query else [it["question"]]
            cfg = p.retrieval_config(use_dense=v.dense, use_bm25=v.bm25, use_rerank=v.rerank, rerank_k=20, fused_k=25)
            t = time.perf_counter()
            results, _ = p.retriever.retrieve(queries, cfg=cfg, rerank_query=it["question"])
            latencies.append((time.perf_counter() - t) * 1000)
            ranked = [r.source.id for r in results]
            rel = set(it["relevant_sources"])
            rows.append({
                "hit@1": hit_at_k(ranked, rel, 1), "recall@3": recall_at_k(ranked, rel, 3),
                "recall@5": recall_at_k(ranked, rel, 5), "precision@3": precision_at_k(ranked, rel, 3),
                "mrr@10": reciprocal_rank(ranked, rel, 10), "ndcg@10": ndcg_at_k(ranked, rel, 10),
            })
        table[v.name] = {k: round(mean([r[k] for r in rows]), 3) for k in rows[0]}
        table[v.name]["p50_latency_ms"] = round(statistics.median(latencies), 1)
    return {"n_questions": len(in_scope), "variants": table}


def eval_generation(p: RagPipeline, items: list[dict], limit: int | None) -> dict:
    sample = items[:limit] if limit else items
    per_q = []
    for it in sample:
        t = time.perf_counter()
        try:
            ans = p.answer(it["question"])
            err = None
        except Exception as exc:  # record and continue; a failure is a result too
            ans, err = None, f"{type(exc).__name__}: {exc}"
        latency = (time.perf_counter() - t) * 1000
        rel = set(it["relevant_sources"])
        rec = {"id": it["id"], "type": it["type"], "latency_ms": round(latency), "error": err}
        if ans is not None:
            flags = ans.safety.flags
            tier = ("general_knowledge" if "unverified_general_knowledge" in flags else "wikipedia" if "wikipedia" in flags
                    else "external" if "external_sources" in flags else "local" if ans.claims else "none")
            # Relevance labels exist only for the local library, so citation accuracy is scored on local answers.
            evidence, *_ = p.retrieve_evidence(it["question"]) if tier == "local" else ([], None, None, None)
            by_ev = {e.id: e.source_id for e in evidence}
            cited_ok = [any(by_ev.get(e) in rel for e in c.evidence_ids) for c in ans.claims] if tier == "local" else []
            rec.update({
                "tier": tier,
                "status": ans.status.value,
                "accepted_claims": len(ans.claims),
                "rejected_claims": len(ans.rejected_claims),
                "citation_source_correct": sum(cited_ok),
                "rejection_reasons": [c.reason for c in ans.rejected_claims],
                "answer": ans.answer,
            })
        per_q.append(rec)

    ins = [r for r in per_q if r["type"] == "in_scope" and not r["error"]]
    oos = [r for r in per_q if r["type"] == "out_of_scope" and not r["error"]]
    accepted = sum(r["accepted_claims"] for r in ins)
    generated = accepted + sum(r["rejected_claims"] for r in ins)
    local_accepted = sum(r["accepted_claims"] for r in ins if r.get("tier") == "local")
    tiers: dict[str, int] = {}
    for r in ins:
        tiers[r.get("tier", "none")] = tiers.get(r.get("tier", "none"), 0) + 1
    return {
        "n": len(per_q),
        "errors": sum(1 for r in per_q if r["error"]),
        "answered_rate_in_scope": round(mean([r["status"] == "answered" for r in ins]), 3),
        # answered with verified citations (local library, MedlinePlus/MeSH/FDA, Wikipedia)
        "answered_with_sources_rate_in_scope": round(mean([r.get("tier") in ("local", "external", "wikipedia") for r in ins]), 3),
        "answered_by_tier_in_scope": tiers,
        "abstention_rate_out_of_scope": round(mean([r["status"] == "insufficient_evidence" for r in oos]), 3) if oos else None,
        # Of the claims the LLM generated, the share that passed citation validation (NLI + numbers + safety).
        "claim_support_rate": round(accepted / generated, 3) if generated else None,
        # Of the claims shown to users, the share citing a passage from a source labelled relevant.
        "citation_accuracy_local": round(sum(r["citation_source_correct"] for r in ins) / local_accepted, 3) if local_accepted else None,
        "p50_latency_ms": round(statistics.median([r["latency_ms"] for r in per_q]), 0) if per_q else None,
        "per_question": per_q,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generation", action="store_true", help="also run the full pipeline with the LLM")
    ap.add_argument("--limit", type=int, default=None, help="max questions for --generation")
    args = ap.parse_args(argv)

    p = RagPipeline()
    items = load_dataset()
    report = {"created": datetime.now().isoformat(timespec="seconds"),
              "models": {"embedding": p.embedder.model_id, "reranker": p.reranker.model_id, "nli": p.nli.model_id,
                         "llm": p.llm.model},
              "index": p.db.stats(), "retrieval": eval_retrieval(p, items)}
    print(json.dumps(report["retrieval"], indent=2))
    if args.generation:
        report["generation"] = eval_generation(p, items, args.limit)
        print(json.dumps({k: v for k, v in report["generation"].items() if k != "per_question"}, indent=2))
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
