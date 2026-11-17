"""Ingest trusted sources: fetch -> load -> clean -> section -> chunk -> embed -> store."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import SERVICE_ROOT, Settings
from ..models import Embedder
from ..schemas import SourceRecord, SourceSpec
from ..store.knowledge_db import KnowledgeDB
from ..store.vector_store import VectorStore
from .chunking import build_sections, chunk_section
from .loaders import LoadedDocument, assert_trusted, load_html, load_pdf, load_spl

log = logging.getLogger(__name__)

USER_AGENT = "AyuMitraAI-KnowledgeIngest/0.1 (educational health information; respects robots and rate limits)"


@dataclass
class IngestResult:
    source_id: str
    sections: int
    chunks: int
    skipped: bool = False
    error: str | None = None


# Bump when chunking or parsing logic changes. v2: lists stay with their "...:" lead-in sentence.
CHUNKER_VERSION = "2"


def load_manifest(path: Path) -> list[SourceSpec]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    specs = [SourceSpec(**item) for item in data["sources"]]
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source ids in manifest")
    return specs


def fetch(spec: SourceSpec, raw_dir: Path, *, refresh: bool = False, delay_s: float = 1.0) -> tuple[bytes, str]:
    """Return (content, kind). Downloads are cached under data/raw so re-runs don't hit the site."""
    if spec.path:
        p = (SERVICE_ROOT / spec.path).resolve()
        return p.read_bytes(), "pdf" if p.suffix.lower() == ".pdf" else "html"

    import httpx

    assert spec.url
    assert_trusted(spec.url)
    path = spec.url.lower().split("?")[0]
    kind = "pdf" if path.endswith(".pdf") else "spl" if path.endswith(".xml") else "html"
    cache = raw_dir / f"{spec.id}.{kind}"
    if cache.exists() and not refresh:
        return cache.read_bytes(), kind
    time.sleep(delay_s)  # be polite to public health sites
    resp = httpx.get(spec.url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    assert_trusted(str(resp.url))  # redirects must stay on trusted hosts
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(resp.content)
    return resp.content, kind


def parse(spec: SourceSpec, content: bytes, kind: str, raw_dir: Path) -> LoadedDocument:
    if kind == "pdf":
        tmp = raw_dir / f"{spec.id}.pdf"
        if not tmp.exists():
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(content)
        return load_pdf(tmp)
    if kind == "spl":
        return load_spl(content.decode("utf-8", errors="replace"))
    return load_html(content.decode("utf-8", errors="replace"), content_selector=spec.content_selector,
                     skip_headings=spec.skip_headings)


class Ingestor:
    def __init__(self, settings: Settings, embedder: Embedder, db: KnowledgeDB, vectors: VectorStore):
        self.s, self.embedder, self.db, self.vectors = settings, embedder, db, vectors

    def ingest(self, spec: SourceSpec, *, refresh: bool = False, content: tuple[bytes, str] | None = None) -> IngestResult:
        raw, kind = content or fetch(spec, self.s.raw_dir, refresh=refresh)
        # The fingerprint covers the raw page *and* how it is chunked, so a chunking change re-indexes
        # every source from the cached pages instead of silently keeping the old chunks.
        recipe = f"{CHUNKER_VERSION}|{self.s.chunk_target_words}|{self.s.chunk_max_words}|"                  f"{self.s.chunk_overlap_sentences}|{self.s.semantic_split_threshold}|{self.embedder.model_id}"
        checksum = hashlib.sha256(raw + recipe.encode()).hexdigest()
        existing = self.db.get_source(spec.id)
        if existing and existing.checksum == checksum and not refresh and self.vectors.count(spec.domain) > 0:
            return IngestResult(spec.id, 0, 0, skipped=True)

        doc = parse(spec, raw, kind, self.s.raw_dir)
        if not doc.sections:
            return IngestResult(spec.id, 0, 0, error="No content extracted (check content_selector).")

        sections = build_sections(spec.id, doc, self.s.parent_max_words)
        title = spec.title or doc.title
        chunks = []
        for sec in sections:
            chunks.extend(
                chunk_section(
                    sec, domain=spec.domain, title=title, target_words=self.s.chunk_target_words,
                    max_words=self.s.chunk_max_words, overlap_sentences=self.s.chunk_overlap_sentences,
                    embedder=self.embedder, semantic_threshold=self.s.semantic_split_threshold,
                )
            )
        record = SourceRecord(
            id=spec.id, title=title, url=spec.url, domain=spec.domain, publisher=spec.publisher, license=spec.license,
            published_date=doc.published_date, ingested_at=datetime.now(UTC).isoformat(timespec="seconds"),
            checksum=checksum,
        )
        if existing:
            self.vectors.delete_source(spec.id, existing.domain)
        self.db.replace_source(record, sections, chunks)
        self.vectors.upsert(chunks, extra_meta={spec.id: {"publisher": spec.publisher, "url": spec.url or ""}})
        log.info("Ingested %s: %d sections, %d chunks", spec.id, len(sections), len(chunks))
        return IngestResult(spec.id, len(sections), len(chunks))
