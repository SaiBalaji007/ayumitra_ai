"""
SQLite store for the medical knowledge base: sources, sections (parents) and chunks.

It's the source of truth. ChromaDB holds only vectors keyed by chunk id, BM25 indexes are rebuilt
from here, and parent sections are looked up here. This store holds *public* medical knowledge
only; private patient documents never enter it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

from ..schemas import Chunk, Domain, Section, SourceRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT, domain TEXT NOT NULL, publisher TEXT NOT NULL,
    license TEXT NOT NULL, published_date TEXT, ingested_at TEXT NOT NULL, checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    heading_path TEXT NOT NULL, text TEXT NOT NULL, page INTEGER, ord INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE, domain TEXT NOT NULL,
    text TEXT NOT NULL, embed_text TEXT NOT NULL, heading_path TEXT NOT NULL, page INTEGER,
    ord INTEGER NOT NULL, word_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_domain ON chunks(domain);
CREATE INDEX IF NOT EXISTS ix_chunks_source ON chunks(source_id);
"""


class KnowledgeDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- writes ---

    def replace_source(self, source: SourceRecord, sections: list[Section], chunks: list[Chunk]) -> None:
        """Atomically replace everything stored for one source (re-ingestion is idempotent)."""
        with self._conn() as c:
            c.execute("DELETE FROM sources WHERE id = ?", (source.id,))
            c.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)",
                (source.id, source.title, source.url, source.domain.value, source.publisher, source.license,
                 source.published_date, source.ingested_at, source.checksum),
            )
            c.executemany(
                "INSERT INTO sections VALUES (?,?,?,?,?,?)",
                [(s.id, s.source_id, json.dumps(s.heading_path), s.text, s.page, s.order) for s in sections],
            )
            c.executemany(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(ch.id, ch.source_id, ch.section_id, ch.domain.value, ch.text, ch.embed_text,
                  json.dumps(ch.heading_path), ch.page, ch.order, ch.word_count) for ch in chunks],
            )

    def delete_source(self, source_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    # --- reads ---

    @staticmethod
    def _source(row) -> SourceRecord:
        return SourceRecord(**{k: row[k] for k in row.keys()})

    @staticmethod
    def _chunk(row) -> Chunk:
        return Chunk(
            id=row["id"], source_id=row["source_id"], section_id=row["section_id"], domain=Domain(row["domain"]),
            text=row["text"], embed_text=row["embed_text"], heading_path=json.loads(row["heading_path"]),
            page=row["page"], order=row["ord"], word_count=row["word_count"],
        )

    def get_source(self, source_id: str) -> SourceRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._source(row) if row else None

    def sources(self, domain: Domain | None = None) -> list[SourceRecord]:
        q, args = "SELECT * FROM sources", ()
        if domain:
            q, args = q + " WHERE domain = ?", (domain.value,)
        with self._conn() as c:
            return [self._source(r) for r in c.execute(q + " ORDER BY id", args)]

    def chunks(self, domain: Domain | None = None) -> list[Chunk]:
        q, args = "SELECT * FROM chunks", ()
        if domain:
            q, args = q + " WHERE domain = ?", (domain.value,)
        with self._conn() as c:
            return [self._chunk(r) for r in c.execute(q + " ORDER BY source_id, id", args)]

    def chunks_by_id(self, ids: Iterable[str]) -> dict[str, Chunk]:
        ids = list(ids)
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self._conn() as c:
            return {r["id"]: self._chunk(r) for r in c.execute(f"SELECT * FROM chunks WHERE id IN ({marks})", ids)}

    def section(self, section_id: str) -> Section | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
        if not r:
            return None
        return Section(id=r["id"], source_id=r["source_id"], heading_path=json.loads(r["heading_path"]),
                       text=r["text"], page=r["page"], order=r["ord"])

    def stats(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT domain, COUNT(DISTINCT source_id) AS sources, COUNT(*) AS chunks FROM chunks GROUP BY domain"
            ).fetchall()
        return {r["domain"]: {"sources": r["sources"], "chunks": r["chunks"]} for r in rows}
