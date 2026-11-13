# AyuMitra AI: Development Status

This is the source of truth for what actually exists. It is updated at every milestone commit.

| Status | Meaning |
|---|---|
| ⬜ **Not started** | No working code. Folders, placeholders or model fields alone don't count. |
| 🟨 **In progress** | Some working code exists, but it's incomplete or has no automated tests. |
| 🟦 **Implemented** | Works end to end, but automated tests or evaluation are still missing. |
| ✅ **Tested** | Implemented, covered by automated tests that pass, and (for AI modules) evaluated against a dataset with reported metrics. |

**Rule:** a module is only ✅ when its tests run green in CI or locally. AI modules additionally need
evaluation results (see "Evaluation" below). Pretrained models only, no fine-tuning.

_Last updated: 2026-11-13 (Phase 3)_

---

## Foundation

| Module | Status | Evidence |
|---|---|---|
| Repo structure, env config, Docker Compose files | ✅ Tested | `manage.py check`; frontend build. Compose file is **not run-tested** (no Docker on dev machine). |
| SQLite database (WAL, busy timeout) | ✅ Tested | Migrations applied to `backend/db.sqlite3`; full suite runs on in-memory SQLite |
| Frontend design system, theming, landing, auth pages, app shell | ✅ Tested | Production build and lint clean; manual browser check pending on the developer's side. |
| JWT auth: register, login, refresh, me | ✅ Tested | `accounts/tests.py`, `core/tests.py` |
| Database models (11 entities) | ✅ Tested | Migrations; integrity tests in `medical_reports/tests.py` |
| Per-user data isolation | ✅ Tested | `documents/tests.py::IsolationTests`, `medical_reports/tests.py`, `patients/tests.py` |
| Private document storage | ✅ Tested | Random owner-scoped paths, no public URL, file deleted with its row and with the account |
| Document APIs (upload, list, detail, patch, delete, status, file) | ✅ Tested | `documents/tests.py` |
| Audit log | ✅ Tested | Upload, view, delete, register and profile-update events asserted in tests |
| Celery processing framework | 🟦 Implemented | Pipeline runner tested **eagerly** (no Redis). Not yet run against a real Redis broker or worker. |
| Frontend upload, document list, status, delete | 🟦 Implemented | Builds against the real API; no automated UI tests yet |

## Intelligence modules (the core of the project)

| # | Module | Status | Notes |
|---|---|---|---|
| 2 | PDF text extraction (PyMuPDF) | ⬜ Not started | `DocumentPage` model exists; no extractor yet |
| 2 | OCR (PaddleOCR, Tesseract fallback) | ⬜ Not started | |
| 2 | Table/layout extraction | ⬜ Not started | |
| 3 | Medical NER (spaCy/scispaCy) | ⬜ Not started | |
| 3 | Lab test extraction | ⬜ Not started | `LabParameter` schema exists; nothing populates it |
| 3 | Value and unit extraction | ⬜ Not started | |
| 3 | Reference range extraction | ⬜ Not started | |
| 3 | Medicine name recognition | ⬜ Not started | |
| 3 | Generic/brand normalization (RxNorm) | ⬜ Not started | |
| 3 | Dosage, frequency, duration extraction | ⬜ Not started | `PrescriptionMedicine` schema exists |
| 3 | Confidence scoring and manual verification | ⬜ Not started | Confidence fields exist; no scoring or verification UI |
| 4 | Medical knowledge ingestion | ⬜ Not started | |
| 5 | Embeddings (MiniLM baseline) | ⬜ Not started | |
| 5 | ChromaDB vector store | ⬜ Not started | |
| 6 | Dense retrieval | ⬜ Not started | |
| 6 | BM25 | ⬜ Not started | |
| 6 | Hybrid search and Reciprocal Rank Fusion | ⬜ Not started | |
| 6 | Query rewriting / multi-query | ⬜ Not started | |
| 6 | Cross-encoder reranking | ⬜ Not started | |
| 6 | Contextual compression | ⬜ Not started | |
| 6 | Citation validation | ⬜ Not started | |
| 7 | Qwen2.5-3B-Instruct integration (4-bit NF4) | ⬜ Not started | |
| 8 | LangGraph workflows | ⬜ Not started | |
| 9 | Medical safety validation | ⬜ Not started | |
| – | Health timeline, diet and lifestyle, exports | ⬜ Not started | |

## Evaluation (required before any AI module is ✅)

| Area | Metrics | Status |
|---|---|---|
| OCR | Character error rate, field-level accuracy | ⬜ Not started |
| NLP extraction | Entity/field precision, recall, F1 against labelled reports and prescriptions | ⬜ Not started |
| Retrieval | Recall@K, Precision@K, MRR, NDCG on a labelled question set | ⬜ Not started |
| Generation | Faithfulness, citation accuracy | ⬜ Not started |
| Performance | Retrieval and end-to-end latency | ⬜ Not started |

The evaluation datasets should be small but medically reviewed: printed reports, scans,
handwritten prescriptions and deliberately ambiguous cases. Use only synthetic or properly
de-identified documents; never commit real patient data.

## Implementation order (agreed)
1. Backend foundation · 2. PDF extraction and OCR · 3. Medical NLP · 4. Knowledge ingestion ·
5. Embeddings and ChromaDB · 6. Advanced RAG · 7. Qwen · 8. LangGraph · 9. Safety validation
