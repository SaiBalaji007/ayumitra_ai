"""
Pretrained model wrappers: bi-encoder embeddings, cross-encoder reranker, NLI entailment.

No fine-tuning happens anywhere. Models load lazily and are cached per process.
`Hashing*` classes are deterministic, dependency-free stand-ins used only by tests.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

import numpy as np

from .text import content_terms, tokenize


def _load_cached_first(cls, model_id: str, device: str):
    """Load from the local Hugging Face cache without touching the network (works offline, starts faster);
    only download when the model isn't cached yet (first run on a new machine)."""
    try:
        return cls(model_id, device=device, local_files_only=True)
    except Exception:  # noqa: BLE001 - not cached (or partial): fall back to a normal download
        return cls(model_id, device=device)


def model_slug(model_id: str) -> str:
    """'sentence-transformers/all-MiniLM-L6-v2' -> 'all-minilm-l6-v2' (safe for collection names)."""
    name = model_id.rstrip("/").split("/")[-1].lower()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:40]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_id: str, device: str = "cpu", query_prefix: str = "", passage_prefix: str = ""):
        from sentence_transformers import SentenceTransformer

        self.model_id = model_id
        self._model = _load_cached_first(SentenceTransformer, model_id, device)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self._qp, self._pp = query_prefix, passage_prefix

    def _encode(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode([self._qp + t for t in texts])

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([self._pp + t for t in texts])


class HashingEmbedder:
    """Test double: bag-of-stemmed-terms hashed into a fixed vector, L2-normalised."""

    def __init__(self, dim: int = 256, model_id: str = "test/hashing-embedder"):
        self.model_id, self.dim = model_id, dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in tokenize(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    embed_passages = embed_queries


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------


class Reranker(Protocol):
    model_id: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_id: str, device: str = "cpu"):
        from sentence_transformers import CrossEncoder

        self.model_id = model_id
        self._model = _load_cached_first(CrossEncoder, model_id, device)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        scores = self._model.predict([(query, p) for p in passages], batch_size=16, show_progress_bar=False)
        return [float(s) for s in np.atleast_1d(scores)]


class LexicalReranker:
    """Test double: query-term coverage, mapped to a logit-like range."""

    model_id = "test/lexical-reranker"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = content_terms(query)
        out = []
        for p in passages:
            cov = len(q & content_terms(p)) / len(q) if q else 0.0
            out.append(10 * cov - 5)
        return out


# ---------------------------------------------------------------------------
# Natural language inference (claim verification)
# ---------------------------------------------------------------------------


class EntailmentModel(Protocol):
    model_id: str

    def entailment(self, premise: str, hypotheses: list[str]) -> list[float]: ...


class CrossEncoderNLI:
    """Pretrained NLI cross-encoder; returns P(entailment) for each (premise, hypothesis)."""

    def __init__(self, model_id: str, device: str = "cpu"):
        from sentence_transformers import CrossEncoder

        self.model_id = model_id
        self._model = _load_cached_first(CrossEncoder, model_id, device)
        id2label = getattr(self._model.model.config, "id2label", None) or {}
        labels = {int(k): str(v).lower() for k, v in id2label.items()}
        self._entail_idx = next((i for i, lab in labels.items() if "entail" in lab), 1)

    def entailment(self, premise: str, hypotheses: list[str]) -> list[float]:
        if not hypotheses:
            return []
        logits = np.atleast_2d(self._model.predict([(premise, h) for h in hypotheses], show_progress_bar=False))
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs = exp / exp.sum(axis=1, keepdims=True)
        return [float(p[self._entail_idx]) for p in probs]


class LexicalEntailment:
    """Test double: fraction of hypothesis terms present in the premise."""

    model_id = "test/lexical-entailment"

    def entailment(self, premise: str, hypotheses: list[str]) -> list[float]:
        p = content_terms(premise)
        out = []
        for h in hypotheses:
            terms = content_terms(h)
            out.append(len(terms & p) / len(terms) if terms else 0.0)
        return out


# ---------------------------------------------------------------------------
# Factories (cached so each model loads once per process)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def load_embedder(model_id: str, device: str, query_prefix: str = "", passage_prefix: str = "") -> Embedder:
    if model_id.startswith("test/"):
        return HashingEmbedder(model_id=model_id)
    return SentenceTransformerEmbedder(model_id, device, query_prefix, passage_prefix)


@lru_cache(maxsize=2)
def load_reranker(model_id: str, device: str) -> Reranker:
    return LexicalReranker() if model_id.startswith("test/") else CrossEncoderReranker(model_id, device)


@lru_cache(maxsize=2)
def load_nli(model_id: str, device: str) -> EntailmentModel:
    return LexicalEntailment() if model_id.startswith("test/") else CrossEncoderNLI(model_id, device)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(a @ b / (na * nb)) if na and nb and not math.isnan(na * nb) else 0.0
