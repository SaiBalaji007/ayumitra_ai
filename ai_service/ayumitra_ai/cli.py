"""
Command line:  python -m ayumitra_ai.cli <command>

  ingest [--refresh] [--only ID ...]   fetch, chunk, embed and index sources from knowledge/sources.json
  stats                                show what's indexed (SQLite chunks, Chroma collections)
  retrieve "question"                  show hybrid retrieval results (no LLM)
  ask "question"                       full grounded answer as JSON (needs the LLM server)
  rxnorm                               download RxNorm ingredient/brand names (medicine recognition)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import get_settings


def _pipeline():
    from .pipeline import RagPipeline

    return RagPipeline(get_settings())


def cmd_ingest(args) -> int:
    from .ingestion.pipeline import Ingestor, load_manifest
    from .models import load_embedder
    from .store.knowledge_db import KnowledgeDB
    from .store.vector_store import VectorStore

    s = get_settings()
    embedder = load_embedder(s.embedding_model, s.device, s.embedding_query_prefix, s.embedding_passage_prefix)
    db, vectors = KnowledgeDB(s.knowledge_db), VectorStore(s.chroma_dir, embedder)
    ingestor = Ingestor(s, embedder, db, vectors)
    specs = load_manifest(s.sources_manifest)
    if args.only:
        specs = [sp for sp in specs if sp.id in set(args.only)]
    failures = 0
    for spec in specs:
        try:
            r = ingestor.ingest(spec, refresh=args.refresh)
            status = "unchanged" if r.skipped else (f"ERROR {r.error}" if r.error else f"{r.sections} sections, {r.chunks} chunks")
            failures += bool(r.error)
        except Exception as exc:  # one bad source must not stop the rest
            status, failures = f"ERROR {type(exc).__name__}: {exc}", failures + 1
        print(f"{spec.id:45s} {status}")
    print(json.dumps(db.stats(), indent=2))
    return 1 if failures else 0


def cmd_stats(_args) -> int:
    from .models import load_embedder
    from .store.knowledge_db import KnowledgeDB
    from .store.vector_store import VectorStore

    s = get_settings()
    db = KnowledgeDB(s.knowledge_db)
    print("knowledge db:", json.dumps(db.stats(), indent=2))
    vectors = VectorStore(s.chroma_dir, load_embedder(s.embedding_model, s.device))
    print("chroma collections:", json.dumps(vectors.collections(), indent=2))
    return 0


def cmd_retrieve(args) -> int:
    p = _pipeline()
    evidence, queries, timings, relevant = p.retrieve_evidence(args.question)
    print(json.dumps({"queries": queries, "relevant": relevant, "timings_ms": timings,
                      "evidence": [e.model_dump(exclude={"sentences"}) for e in evidence]}, indent=2, ensure_ascii=False))
    return 0


def cmd_ask(args) -> int:
    p = _pipeline()
    print(p.answer(args.question).model_dump_json(indent=2))
    return 0


def cmd_rxnorm(_args) -> int:
    from .nlp.medicines import download_lexicon

    print(json.dumps(download_lexicon(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ayumitra_ai")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ing = sub.add_parser("ingest")
    p_ing.add_argument("--refresh", action="store_true")
    p_ing.add_argument("--only", nargs="*")
    p_ing.set_defaults(fn=cmd_ingest)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    sub.add_parser("rxnorm").set_defaults(fn=cmd_rxnorm)
    for name, fn in (("retrieve", cmd_retrieve), ("ask", cmd_ask)):
        sp = sub.add_parser(name)
        sp.add_argument("question")
        sp.set_defaults(fn=fn)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
