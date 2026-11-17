"""Data contracts shared by ingestion, retrieval, generation and the API."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Domain(StrEnum):
    """Knowledge is never mixed into one collection: each domain has its own."""

    GENERAL = "general"
    LAB_TESTS = "lab_tests"
    MEDICINES = "medicines"
    NUTRITION = "nutrition"
    LIFESTYLE = "lifestyle"
    GUIDELINES = "guidelines"


class SourceSpec(BaseModel):
    """One entry of knowledge/sources.json: a trusted document to ingest."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    title: str
    url: str | None = None
    path: str | None = None  # local PDF/HTML, relative to the service root
    domain: Domain
    publisher: str
    license: str
    content_selector: str | None = None  # CSS selector of the article body (HTML)
    skip_headings: list[str] = []
    language: str = "en"


class Section(BaseModel):
    """A heading-delimited part of a document. Acts as the parent of its chunks."""

    id: str
    source_id: str
    heading_path: list[str]
    text: str
    page: int | None = None
    order: int


class Chunk(BaseModel):
    id: str
    source_id: str
    section_id: str
    domain: Domain
    text: str             # exact source text, used for citations
    embed_text: str       # text with title/section context, used for embedding
    heading_path: list[str]
    page: int | None = None
    order: int
    word_count: int


class SourceRecord(BaseModel):
    id: str
    title: str
    url: str | None
    domain: Domain
    publisher: str
    license: str
    published_date: str | None = None  # "last updated/reviewed" printed on the source
    ingested_at: str
    checksum: str


class RetrievedChunk(BaseModel):
    chunk: Chunk
    source: SourceRecord
    dense_rank: int | None = None
    bm25_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None
    matched_queries: list[str] = []


class EvidenceSentence(BaseModel):
    text: str
    start: int  # character offsets into chunk.text
    end: int


class Evidence(BaseModel):
    id: str  # "E1", "E2", ... as cited by the model
    chunk_id: str
    source_id: str
    title: str
    url: str | None
    section: str
    page: int | None
    published_date: str | None
    text: str  # compressed passage shown to the model
    sentences: list[EvidenceSentence]
    rerank_score: float | None
    publisher: str | None = None
    external: bool = False  # fetched live from an external trusted source (not the local knowledge base)


CLAIM_SECTIONS = ("direct_answer", "explanation", "key_points", "see_doctor")


class Claim(BaseModel):
    text: str
    evidence_ids: list[str]
    quote: str | None = None
    section: str = "explanation"  # one of CLAIM_SECTIONS


class ValidatedClaim(Claim):
    supported: bool
    support_score: float
    method: str
    reason: str = ""


class Citation(BaseModel):
    id: str
    title: str
    url: str | None
    section: str
    page: int | None
    published_date: str | None
    quote: str
    publisher: str | None = None
    external: bool = False


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REFUSED = "refused"


class SafetyReport(BaseModel):
    flags: list[str] = []
    urgent: bool = False
    urgent_message: str | None = None
    notices: list[str] = []
    disclaimer: str = (
        "AyuMitra AI provides general health information from trusted sources. It is not a diagnosis "
        "or a substitute for advice from your doctor or pharmacist."
    )


class RagAnswer(BaseModel):
    question: str
    status: AnswerStatus
    answer: str
    claims: list[ValidatedClaim] = []
    rejected_claims: list[ValidatedClaim] = []
    citations: list[Citation] = []
    safety: SafetyReport = SafetyReport()
    queries: list[str] = []
    timings_ms: dict[str, float] = {}
    model: dict[str, str] = {}
