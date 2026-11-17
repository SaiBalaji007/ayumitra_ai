"""
HTTP API for the AI service. Django calls this; browsers never do.

  GET  /health          liveness, model ids, index sizes, LLM reachability
  POST /v1/ask          grounded answer (structured JSON)
  POST /v1/retrieve     evidence only (no LLM), for debugging and evaluation

Run:  uvicorn ayumitra_ai.api:app --host 127.0.0.1 --port 8001
Set AYUMITRA_SERVICE_TOKEN so only the Django backend can call it.
"""

from __future__ import annotations

import os
import secrets
import threading
from contextlib import asynccontextmanager
from functools import lru_cache, wraps

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .llm.client import LLMError
from .schemas import Domain, Evidence, RagAnswer

# Sync endpoints run in a thread pool, and lru_cache does not stop two threads from building the same
# object at once. Two concurrent RagPipeline() calls open two Chroma clients on one directory, which
# fails ("Could not connect to tenant default_tenant"). One re-entrant lock serialises construction.
_build_lock = threading.RLock()


def singleton(fn):
    cached = lru_cache(maxsize=None)(fn)

    @wraps(fn)
    def wrapper():
        with _build_lock:
            return cached()

    wrapper.cache_clear = cached.cache_clear
    return wrapper


@asynccontextmanager
async def lifespan(_app):
    # Load models in the background at startup so the first user request isn't the slow one;
    # requests that arrive meanwhile simply wait on the lock.
    threading.Thread(target=lambda: (pipeline(), agent()), name="warmup", daemon=True).start()
    yield


app = FastAPI(title="AyuMitra AI service", version="0.1.0", lifespan=lifespan)


@singleton
def pipeline():
    from .pipeline import RagPipeline

    return RagPipeline()


def require_token(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("AYUMITRA_SERVICE_TOKEN", "")
    if not expected:
        return  # local development without a token
    supplied = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid service token")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    domains: list[Domain] | None = None


class RetrieveResponse(BaseModel):
    queries: list[str]
    relevant: bool
    evidence: list[Evidence]
    timings_ms: dict[str, float]


@app.get("/health")
def health():
    p = pipeline()
    return {
        "status": "ok",
        "models": {"embedding": p.embedder.model_id, "reranker": getattr(p.reranker, "model_id", None),
                   "nli": getattr(p.nli, "model_id", None), "llm": p.llm.model},
        "llm_reachable": p.llm.health(),
        "index": p.db.stats(),
    }


@app.post("/v1/ask", response_model=RagAnswer, dependencies=[Depends(require_token)])
def ask(req: AskRequest):
    try:
        return pipeline().answer(req.question, domains=req.domains)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=f"Language model unavailable: {exc}") from exc
    except ValueError as exc:  # unparsable model output
        raise HTTPException(status_code=502, detail="The language model returned an invalid response.") from exc


@app.post("/v1/retrieve", response_model=RetrieveResponse, dependencies=[Depends(require_token)])
def retrieve(req: AskRequest):
    evidence, queries, timings, relevant = pipeline().retrieve_evidence(req.question, domains=req.domains)
    return RetrieveResponse(queries=queries, relevant=relevant, evidence=evidence, timings_ms=timings)


# ---------------------------------------------------------------------------
# Document analysis (stateless: bytes in, structure out; nothing is stored here)
# ---------------------------------------------------------------------------

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024


@singleton
def lexicon():
    from .nlp.medicines import default_lexicon

    return default_lexicon()


def analyze_bytes(data: bytes, content_type: str) -> dict:
    """OCR/text extraction -> classification -> lab or prescription extraction. No LLM involved."""
    from .documents.classify import classify
    from .documents.extract import extract_document
    from .nlp.lab_extraction import extract_from_table, extract_lab_results
    from .nlp.prescriptions import extract_prescription

    ex = extract_document(data, content_type)
    text = ex.text
    cls = classify(text)
    labs, items = [], []
    for page in ex.pages:
        # OCR pages: text is already rebuilt into visual rows; each row inherits the page's OCR confidence.
        row_lines = page.text.splitlines()
        confs = [page.confidence] * len(row_lines) if page.method != "text_layer" else None
        if cls.document_type == "lab_report":
            found = extract_lab_results(row_lines, page=page.page_number, line_confidences=confs)
            if not found:
                for t in page.tables:
                    found.extend(extract_from_table(t.rows, page=page.page_number))
            labs.extend(r.to_dict() for r in found)
        elif cls.document_type == "prescription":
            items.extend(i.to_dict() for i in extract_prescription(row_lines, lexicon(), confs))
    return {
        "extraction": ex.to_dict(),
        "classification": {"document_type": cls.document_type, "confidence": cls.confidence, "scores": cls.scores,
                           "cues": cls.cues},
        "lab_results": labs,
        "prescription_items": items,
        "versions": {"service": app.version},
    }


@app.post("/v1/documents/analyze", dependencies=[Depends(require_token)])
async def analyze_document(request: Request):
    content_type = request.headers.get("x-document-content-type", "")
    if content_type not in ("application/pdf", "image/png", "image/jpeg"):
        raise HTTPException(status_code=415, detail="Send X-Document-Content-Type: application/pdf, image/png or image/jpeg")
    data = await request.body()
    if not data or len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Document is empty or too large")
    try:
        return analyze_bytes(data, content_type)
    except Exception as exc:  # corrupt files etc.: report, never crash the service
        raise HTTPException(status_code=422, detail=f"Could not read the document: {type(exc).__name__}") from exc


# ---------------------------------------------------------------------------
# Agent workflows (LangGraph)
# ---------------------------------------------------------------------------


@singleton
def agent():
    from .agents.graph import AyuMitraAgent

    return AyuMitraAgent(pipeline(), lexicon())


class AgentRequest(BaseModel):
    question: str | None = Field(default=None, max_length=1000)
    document_text: str | None = Field(default=None, max_length=200_000)
    report_results: list[dict] | None = None
    lab_results: list[dict] | None = None
    mode: str | None = Field(default=None, pattern="^(explain|education)$")
    previous_question: str | None = Field(default=None, max_length=1000)  # for follow-up questions


class MedicineInfoRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=10)


@app.post("/v1/medicine-info", dependencies=[Depends(require_token)])
def medicine_info(req: MedicineInfoRequest):
    """FDA label information for medicines identified on a prescription. Only call with names that were
    exactly matched (RxNorm) or confirmed by the user: never with a guessed name."""
    p = pipeline()
    out = []
    for name in dict.fromkeys(n.strip() for n in req.names if n.strip()):
        info = p.external.medicine_info(name) if p.external is not None else None
        out.append(info or {"query": name, "not_found": True})
    return {"medicines": out}


@app.post("/v1/agent", dependencies=[Depends(require_token)])
def run_agent(req: AgentRequest):
    if not (req.question or req.document_text or req.lab_results):
        raise HTTPException(status_code=400, detail="Provide a question, document_text or lab_results")
    try:
        state = agent().run(**{k: v for k, v in req.model_dump().items() if v})
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=f"Language model unavailable: {exc}") from exc
    keys = ("intent", "document_type", "safety", "lab_results", "prescription_items", "explanations", "answer",
            "messages", "trace")
    return {k: state.get(k) for k in keys}


# ---------------------------------------------------------------------------
# PDF export (Phase 11): lays out already-validated data; generates no new content
# ---------------------------------------------------------------------------


@app.post("/v1/export/report", dependencies=[Depends(require_token)])
def export_report(data: dict):
    from fastapi.responses import Response as RawResponse

    from .export import render_report_pdf

    if not isinstance(data.get("parameters"), list):
        raise HTTPException(status_code=400, detail="parameters list required")
    return RawResponse(content=render_report_pdf(data), media_type="application/pdf")
