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


def _needs_vision(ex, items: list[dict]) -> bool:
    """Use the (slower) vision reader only where OCR struggles: handwriting / photos / scans."""
    if any(p.method == "text_layer" for p in ex.pages):
        return False  # digital PDF: the text layer is exact
    conf = min((p.confidence for p in ex.pages if p.confidence is not None), default=0.0)
    incomplete = sum(1 for it in items if not it.get("frequency") or "name" in it.get("fields_needing_review", []))
    return not items or conf < 0.9 or incomplete > len(items) / 2


def read_prescription_with_vision(data: bytes, content_type: str, ex, ocr_items: list[dict]) -> list[dict] | None:
    """Medicine lines read by the local vision model, normalised by the same parser and lexicon as OCR text,
    and cross-checked against the OCR text of the page. Returns None to keep the OCR result."""
    from .documents import vlm
    from .nlp.prescriptions import parse_item

    if not vlm.available() or not _needs_vision(ex, ocr_items):
        return None
    rows = vlm.read_prescription(data, content_type)
    if not rows or len(rows) < len(ocr_items):
        return None
    from .nlp.prescriptions import FORMS, frequency_of

    page_text = ex.text
    out = []
    for n, row in enumerate(rows, 1):
        item = parse_item(vlm.as_line(row), n, lexicon())
        # The model already separates the fields: use each one as read (the line re-parse only fills gaps),
        # so a dose such as "1 x 1" is never mistaken for the frequency "1 cap once morning".
        item.name_as_written = row["name"]
        item.dosage_form = FORMS.get(row["form"].lower().rstrip("."), item.dosage_form) if row["form"] else item.dosage_form
        for f in ("strength", "timing", "duration"):
            if row[f] and not (f == "timing" and row[f].lower() == "oral"):
                setattr(item, f, row[f])
        if row["frequency"]:
            item.frequency = row["frequency"]
            item.frequency_reading = frequency_of(row["frequency"])
        match = lexicon().match(row["name"])
        item.medicine = match.to_dict()
        known = match.status.startswith("exact") or match.status == "indian_brand"
        conf = {"name": 0.9 if known or vlm.support_in_text(row["name"], page_text) >= 0.75 else 0.6}
        for f in ("strength", "frequency", "timing", "duration"):
            value = getattr(item, f)
            if not value:
                conf[f] = 0.0  # not written (or not read): stays empty, flagged below for the user
            else:  # read by the model; trusted more when the OCR text of the page also shows it
                conf[f] = 0.9 if vlm.support_in_text(value, page_text) >= 0.6 else 0.7
        item.field_confidence = conf
        item.fields_needing_review = [f for f in ("name", "strength", "frequency", "duration") if conf[f] < 0.85]
        present = [v for v in conf.values() if v > 0]
        item.overall_confidence = round(min(present) if present else 0.0, 3)
        d = item.to_dict()
        d["read_by"] = "vision"
        out.append(d)
    return out


def missed_medicine_warnings(ex, items: list[dict]) -> list[str]:
    """Second opinion from the biomedical NER model on READABLE text (digital PDFs, clear printed pages): warn about
    medicine names it finds that are not in the list. Garbled handwriting OCR is skipped (the model only produces
    noise there). Warnings only: nothing is added to the user's medicines."""
    from .nlp import ner

    if not ner.available():
        return []
    readable = [p for p in ex.pages if p.method == "text_layer" or (p.confidence or 0) >= 0.9]
    text = "\n".join(p.text for p in readable)
    if not text.strip():
        return []
    try:
        missed = ner.possibly_missed_medicines(text, [it.get("name_as_written", "") for it in items])
    except Exception:  # the second opinion must never break document processing
        return []
    return [f"This page may also mention “{m}”, which is not in the list below. Please check your prescription "
            f"and add it if it is a medicine." for m in missed[:5]]


def analyze_bytes(data: bytes, content_type: str, document_type: str = "") -> dict:
    """OCR/text extraction -> classification -> lab or prescription extraction. No LLM involved.

    document_type: the user's choice at upload. It decides which extraction runs, because the user
    knows what they uploaded and the keyword classifier can miss on noisy scans; the classifier's own
    verdict is still returned unchanged."""
    from .documents.classify import classify
    from .documents.extract import extract_document, visual_rows
    from .nlp.lab_extraction import extract_from_table, extract_lab_results
    from .nlp.prescriptions import extract_prescription
    from .reference_ranges import typical_ranges

    ex = extract_document(data, content_type)
    text = ex.text
    cls = classify(text)
    kind = document_type if document_type in ("lab_report", "prescription") else cls.document_type
    labs, items = [], []
    for page in ex.pages:
        # OCR pages: text is already rebuilt into visual rows; each row inherits the page's OCR confidence.
        row_lines = page.text.splitlines()
        confs = [page.confidence] * len(row_lines) if page.method != "text_layer" else None
        if kind == "lab_report":
            found = extract_lab_results(row_lines, page=page.page_number, line_confidences=confs)
            if page.method == "text_layer" and page.lines:
                # PDFs that store each table cell as its own line: parse rows rebuilt from positions too,
                # and keep whichever reading finds more results.
                by_rows = extract_lab_results(visual_rows(page.lines), page=page.page_number)
                if len(by_rows) > len(found):
                    found = by_rows
            if not found:
                for t in page.tables:
                    found.extend(extract_from_table(t.rows, page=page.page_number))
            for r in found:
                d = r.to_dict()
                # No range printed on the report: offer cited typical ranges (shown as such, never as the lab's).
                if not d["reference_range_text"]:
                    d["typical_ranges"] = typical_ranges(d["normalized_name"], d["unit"])
                labs.append(d)
        elif kind == "prescription":
            items.extend(i.to_dict() for i in extract_prescription(row_lines, lexicon(), confs))
    if kind == "prescription":
        vision = read_prescription_with_vision(data, content_type, ex, items)
        if vision is not None:
            items = vision
            ex.warnings.append("Medicines were read from handwriting by AyuMitra's local vision model. "
                               "Please check every line against your prescription before confirming it.")
        ex.warnings.extend(missed_medicine_warnings(ex, items))
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
        return analyze_bytes(data, content_type, request.headers.get("x-document-type", "").strip().lower())
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
