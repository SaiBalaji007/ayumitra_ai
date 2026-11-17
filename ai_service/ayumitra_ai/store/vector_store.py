"""
ChromaDB vector store, one collection per (knowledge domain × embedding model).

Collection name: kb_<domain>__<model-slug>__v<schema>, e.g. kb_lab_tests__all-minilm-l6-v2__v1
Each collection records its embedding model id and dimension in its metadata, and every operation
checks them. Vectors from two different models therefore can never be mixed or compared.
Private patient documents use a different prefix (`pt_`) and are never part of the knowledge base.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..models import Embedder, model_slug
from ..schemas import Chunk, Domain

SCHEMA_VERSION = 1


class EmbeddingModelMismatch(RuntimeError):
    pass


@dataclass
class DenseHit:
    chunk_id: str
    score: float  # cosine similarity (1 - cosine distance)


def collection_name(domain: Domain, embedding_model: str, schema_version: int = SCHEMA_VERSION) -> str:
    return f"kb_{domain.value}__{model_slug(embedding_model)}__v{schema_version}"


def _meta_value(v):
    """Chroma metadata accepts only str/int/float/bool; drop None and flatten lists."""
    if v is None:
        return None
    if isinstance(v, list):
        return " > ".join(map(str, v))
    return v


class VectorStore:
    def __init__(self, path: Path, embedder: Embedder):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(path), settings=ChromaSettings(anonymized_telemetry=False))
        self.embedder = embedder

    def _collection(self, domain: Domain, create: bool):
        name = collection_name(domain, self.embedder.model_id)
        expected = {"embedding_model": self.embedder.model_id, "embedding_dim": self.embedder.dim}
        if create:
            col = self._client.get_or_create_collection(
                name=name,
                embedding_function=None,
                metadata={"hnsw:space": "cosine", "domain": domain.value, "schema_version": SCHEMA_VERSION, **expected},
            )
        else:
            try:
                col = self._client.get_collection(name=name, embedding_function=None)
            except Exception:  # chroma raises NotFoundError / ValueError depending on version
                return None
        meta = col.metadata or {}
        for key, value in expected.items():
            if meta.get(key) != value:
                raise EmbeddingModelMismatch(
                    f"Collection {name} was built with {key}={meta.get(key)!r}, current embedder has {value!r}. "
                    "Re-ingest into a new collection instead of mixing embedding models."
                )
        return col

    def upsert(self, chunks: list[Chunk], *, extra_meta: dict[str, dict] | None = None) -> int:
        if not chunks:
            return 0
        by_domain: dict[Domain, list[Chunk]] = {}
        for ch in chunks:
            by_domain.setdefault(ch.domain, []).append(ch)
        total = 0
        for domain, items in by_domain.items():
            col = self._collection(domain, create=True)
            vectors = self.embedder.embed_passages([c.embed_text for c in items])
            metas = []
            for c in items:
                m = {
                    "source_id": c.source_id, "section_id": c.section_id, "domain": c.domain.value,
                    "heading_path": c.heading_path, "page": c.page, "order": c.order,
                    **((extra_meta or {}).get(c.source_id, {})),
                }
                metas.append({k: _meta_value(v) for k, v in m.items() if _meta_value(v) is not None})
            for start in range(0, len(items), 256):
                sl = slice(start, start + 256)
                col.upsert(ids=[c.id for c in items[sl]], embeddings=vectors[sl].tolist(), metadatas=metas[sl])
            total += len(items)
        return total

    def delete_source(self, source_id: str, domain: Domain) -> None:
        col = self._collection(domain, create=False)
        if col is not None:
            col.delete(where={"source_id": source_id})

    def search(self, query_vec: np.ndarray, domains: list[Domain], k: int, where: dict | None = None) -> list[DenseHit]:
        hits: list[DenseHit] = []
        for domain in domains:
            col = self._collection(domain, create=False)
            if col is None or col.count() == 0:
                continue
            res = col.query(
                query_embeddings=[query_vec.tolist()], n_results=min(k, col.count()), where=where or None,
                include=["distances"],
            )
            for cid, dist in zip(res["ids"][0], res["distances"][0], strict=True):
                hits.append(DenseHit(chunk_id=cid, score=1.0 - float(dist)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def count(self, domain: Domain) -> int:
        col = self._collection(domain, create=False)
        return col.count() if col is not None else 0

    def collections(self) -> list[dict]:
        out = []
        for col in self._client.list_collections():
            c = self._client.get_collection(col if isinstance(col, str) else col.name, embedding_function=None)
            out.append({"name": c.name, "count": c.count(), **(c.metadata or {})})
        return out
