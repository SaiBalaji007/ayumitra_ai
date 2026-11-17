# AyuMitra AI: Development Status

This is the source of truth for what actually exists. It is updated after every stage.

| Status | Meaning |
|---|---|
| ⬜ **Not started** | No working code. Folders, placeholders or model fields alone don't count. |
| 🟨 **In progress** | Code exists but has not yet been run, or is incomplete, or its tests have not passed yet. |
| 🟦 **Implemented** | Runs end to end, but automated tests or evaluation are still missing. |
| ✅ **Tested** | Implemented, covered by automated tests that pass, and (for AI modules) evaluated against a dataset with reported metrics. |

**Rule:** a module is only ✅ when its tests run green locally. AI modules additionally need
evaluation results (see "Evaluation" below). Pretrained models only, no fine-tuning.

_Last updated: 2026-11-14: Phase 1 (RAG), Phase 2 (hospital finder) and Phase 3 (prescription analyzer) implemented, tested and verified in the browser._

**Running locally:** frontend http://localhost:5173 · backend http://127.0.0.1:8000/api/ · AI service http://127.0.0.1:8001 (health: `/health`) · Qwen llama-server http://127.0.0.1:8081 (running, `/health` ok). Document worker: `python manage.py process_documents` (SQLite queue, `DOCUMENT_PROCESSING_ENABLED=True` in `.env`).

---

## Foundation

| Module | Status | Evidence |
|---|---|---|
| Repo structure, env config | ✅ Tested | `manage.py check`, `check --deploy` (only the intentional HSTS-preload warning) |
| Docker Compose, Dockerfiles, nginx, deployment guide | 🟨 In progress | Written, **not run-tested** (no Docker here). Deployment is postponed until the app works locally |
| SQLite database (WAL, busy timeout, IMMEDIATE transactions) | ✅ Tested | Migrations applied; full backend suite runs on SQLite |
| JWT auth, account settings (name, password change, account deletion) | ✅ Tested | `accounts/tests.py`, `accounts/test_settings.py` |
| Per-user data isolation | ✅ Tested | documents, reports, patients, assistant and recommendations tests |
| Private document storage, document APIs, audit log | ✅ Tested | `documents/tests.py` |
| Document processing queue (`db` backend / Celery) | 🟦 Implemented | Tested eagerly; not yet run against a real Redis broker |
| Backend test suite | ✅ Tested | 116 tests pass (2026-11-14, incl. Phase 2 and 3) (`python manage.py test`); document tests no longer depend on the local `.env` |
| Frontend build, lint, unit tests | ✅ Tested | build, oxlint, 12 tests pass; every nav route checked in headless Edge (no console errors, no blank pages) |

## Intelligence modules (`ai_service/ayumitra_ai`)

AI test suite: **144 passed** (`.venv/Scripts/python -m pytest`), real models: all-MiniLM-L6-v2 (384-d),
ms-marco-MiniLM-L-6-v2 reranker, nli-deberta-v3-small citation check.

| Module | Status | Notes |
|---|---|---|
| PDF text extraction (PyMuPDF, tables) | ✅ Tested | Digital PDFs: CER 0.000, field F1 1.000 (OCR eval) |
| OCR (RapidOCR ONNX) | ✅ Tested | Printed/scanned images CER 0.8–2.2 %. Tesseract binary not installed (fallback unused) |
| Lab test, value, unit and reference-range extraction | ✅ Tested | Digital PDF F1 1.00; image F1 0.70 printed / 0.53 scanned (recall is the weak point). Fixed on real/synthetic reports: names ending in digits (T3, B12); OCR misreads (HbAlc→HbA1c, flagged); status column ("Normal"); units mg/L, g/L, nmol/L, mL/min, etc.; header barcodes/IDs no longer read as results (one crashed the reports page); unreadable units ("7p/3w") kept + flagged; a reference range is never reported as the value |
| Medicine recognition and RxNorm normalisation | ✅ Tested | Exact match only; fuzzy matches are suggestions |
| Prescription parsing | ✅ Tested | Printed/scanned F1 0.95–0.98 (all wrong fields flagged); handwritten F1 0.57 (synthetic handwriting) |
| Knowledge ingestion (57 public sources) | ✅ Tested | 57/57 sources, 725 chunks (lab_tests 356, medicines 200, general 56, nutrition 61, lifestyle 52). Added MedlinePlus Vitamin E and Vitamins. Added TSH, T4, ALT, AST, bilirubin, sodium, potassium, ESR, CRP, RBC pages. Chunker v2 keeps lists with their "...:" lead-in; changing the chunker re-indexes automatically |
| Embeddings + ChromaDB | ✅ Tested | 5 collections `kb_<domain>__all-minilm-l6-v2__v1`, model/dimension guard |
| Dense, BM25, hybrid, RRF, multi-query, reranking | ✅ Tested | See retrieval evaluation below |
| Answer tiers (local → external → Wikipedia → general knowledge) | ✅ Tested | 1) local ChromaDB library; 2) live MedlinePlus health topics, NLM MeSH definitions and openFDA drug labels (no dosage sections); 3) Wikipedia, only for questions confirmed to be about health (User-Agent contact = project repo URL, `AYUMITRA_WIKIPEDIA_CONTACT` in `ai_service/.env`); 4) Qwen general knowledge, only for health questions, labelled "not checked against a source", sentence-level safety filter, links stripped. Tiers 1–3 are cited and citation-validated; non-health questions are declined |
| Scope classification | ✅ Tested | Keyword list no longer declines anything: unknown wording goes to `scope_check` (local relevance → external relevance → Qwen yes/no health check). Fixed: "TOCOPHEROL" / "What is tocopherol?" were declined before retrieval. Synonyms (tocopherol→vitamin E, cobalamin→B12, ...) used for search, reranking and generation |
| Answer format and quality | ✅ Tested | Sections: Direct answer, Detailed explanation, Important points, When to consult a doctor; sources with publisher and link. Rejected: fragments ("... are listed in Table 1"), duplicates, garbled terms ("TOcoproil"), conditional "if you have" no longer mistaken for a diagnosis, "stop/start/change your medicine" blocked. Follow-ups use the previous question of the conversation |
| Contextual compression, citation validation (NLI) | ✅ Tested | Live with Qwen. Fixed: compression and evidence de-duplication cut lists apart ("low hemoglobin may be a sign of:" without its items), and "vitamin B-12" was treated as the number 12, both causing correct answers to be rejected |
| Qwen2.5-3B-Instruct (llama.cpp CPU, Q4_K_M GGUF) | ✅ Tested | llama-server b12360, 8 threads, ~3.4 GB RAM; ~8–27 s generation per answer on CPU |
| LangGraph agent | ✅ Tested | Unit tests pass (langgraph installed) |
| Medical safety layer | ✅ Tested | Unit tests |
| AI service API | ✅ Tested | Fixed: concurrent first requests built two Chroma clients and crashed; now a lock + startup warm-up (6 concurrent requests OK, regression test added) |

## Integration (Django + React)

| Module | Status | Notes |
|---|---|---|
| Backend → AI service client | ✅ Tested | Live: browser → Django → AI service (token) → ChromaDB + Qwen → browser |
| Assistant page | ✅ Tested | 5 test questions answered in the browser with citations (incl. a question about an uploaded report). Fixed earlier: blank page, raw "Conversation id" error |
| Diet and lifestyle recommendations | ✅ Tested | `/api/recommendations/`: curated, sourced, from the user's latest results + profile; 10 tests; checked in browser |
| Reports, prescriptions, timeline, settings | ✅ Tested | Backend tests; pages checked in browser |
| Report upload → extraction → explanations | ✅ Tested | Live: synthetic PDF 7/7 rows exact; a real-world Vitamin E report extracted correctly after fixes; abnormal-value explanations: 4 of 6 answered with citations, 2 abstained (low HbA1c: not covered by sources; high TSH: model added unsupported details, rejected by the citation check) |

## Phase 2: Find Hospitals & Medical Shops

| Module | Status | Evidence |
|---|---|---|
| Backend `GET /api/care/nearby/?city=&locality=&category=all\|hospital\|clinic\|pharmacy\|doctor&radius=2\|5\|10\|20` (`backend/core/nearby.py`) | ✅ Tested | Nominatim geocoding (city/locality centre, India) + Overpass (amenity/healthcare/shop=chemist tags), mirrors tried in turn on 429/502/503/504 with short back-off, 24 h cache, input validation, login required. 7 tests (`core/test_nearby.py`): validation, parsing, de-duplication, distance sort, cache, unknown city, busy mirror fallback, all servers down |
| Providers configurable | ✅ | `GEOCODER_URL`, `OVERPASS_URLS`, `OSM_USER_AGENT` in `.env` (no API keys) |
| Frontend page `/app/nearby` + sidebar button below "Medical reports" | ✅ Tested in browser | Leaflet map (OSM tiles + attribution), coloured markers per category, popups, radius circle, cards (address, distance, phone, hours, website, "Not available" when missing), View on map, Get directions (Google Maps / OSM route) |
| Live browser results (2026-11-14) | ✅ | Noida, Uttar Pradesh (all, 5 km): 118 places (50 hospitals, 39 clinics, 17 doctors, 12 pharmacies); Delhi (hospitals, 2 km): 10; Vizianagaram, Andhra Pradesh (pharmacies, 5 km): 9; invalid city: clear "Couldn't find" message. Data comes only from OpenStreetMap; nothing is invented |

## Phase 3: Prescription Analyzer (simple version)

| Module | Status | Evidence |
|---|---|---|
| Page `/app/prescription-analyzer` + sidebar button below "Medical reports" | ✅ Tested in browser | Drag-and-drop/browse upload (JPG/PNG/PDF, 20 MB, type check), preview, replace/remove, upload progress; sections: OCR text, safety checks, identified medicines (confirm/correct each line, reused editor), schedule, medicine information, confirmed summary, history with delete |
| OCR + preprocessing (`ai_service/ayumitra_ai/documents/preprocess.py`) | ✅ Tested | RapidOCR (PaddleOCR models, ONNX) on the original; if confidence < 0.85 also on an enhanced copy (grayscale, denoise, CLAHE contrast, sharpen, deskew, upscale) and the better read is kept; blurry-photo warning; multi-page PDFs. EasyOCR fallback not added (simple version) |
| Medicine extraction | ✅ Tested | Existing parser: name as written, strength, frequency, timing, duration; RxNorm exact match only; unclear names flagged, never guessed |
| Schedule (`backend/prescriptions/logic.py`) | ✅ Tested | Only from written instructions: "1-0-1" → Morning/Night, "at bedtime" → Night, "BD/TDS" → "N times a day; times not written", "SOS" → when needed |
| Safety checks | ✅ Tested | Unreadable name, missing strength/frequency/duration, duplicate medicines, match with allergies in the user's profile; never suggests stopping/changing/substituting. Pair-wise interaction checking not included (simple version): the label's interaction section is shown instead |
| Medicine information (`POST /v1/medicine-info`, `GET /api/prescriptions/{id}/insights/`) | ✅ Tested | openFDA/DailyMed labels (oral label preferred; uses, side effects, warnings, contraindications, interactions; no dosing), source link + retrieval date, cached 7 days; looked up only for RxNorm-exact or user-confirmed names; Indian brands without a US label show "not found, ask your pharmacist" |
| Tests | ✅ | 7 backend tests (`prescriptions/test_analyzer.py`); browser: synthetic handwritten PNG (3 medicines read, unreadable durations flagged, schedule + FDA info), synthetic printed PDF (3 medicines, no missing fields, schedule + 3 FDA labels), invalid file type rejected with a clear message |

## Evaluation

**Retrieval** (`python -m evaluation.run_eval`, 40 in-scope questions, real index; report `evaluation/reports/eval_20261114_122812.json`):

| Variant | Hit@1 | Recall@5 | MRR@10 | NDCG@10 | p50 latency |
|---|---|---|---|---|---|
| Dense only | 0.925 | 0.942 | 0.942 | 0.940 | 52 ms |
| BM25 only | 0.450 | 0.879 | 0.626 | 0.697 | 5 ms |
| Hybrid (RRF) | 0.825 | 0.950 | 0.880 | 0.903 | 48 ms |
| Hybrid + multi-query | 0.825 | 1.000 | 0.900 | 0.925 | 69 ms |
| **Hybrid + multi-query + rerank (used)** | **0.925** | 0.950 | **0.944** | **0.954** | 848 ms |

**OCR + extraction** (`python -m evaluation.run_ocr_eval`, synthetic fictional documents; latest report `evaluation/reports/ocr_eval_20261114_134515.json`):

| Documents | CER | Field F1 | Wrong fields flagged for review |
|---|---|---|---|
| Lab report, digital PDF | 0.000 | 1.000 | – |
| Lab report, printed image | 0.016 | 0.695 | 100 % |
| Lab report, scanned image | 0.022 | 0.526 | 86 % |
| Prescription, digital PDF | 0.000 | 1.000 | – |
| Prescription, printed image | 0.010 | 0.953 | 100 % |
| Prescription, scanned image | 0.008 | 0.975 | 100 % |
| Prescription, handwritten image | 0.023 | 0.565 | 48 % |

**Generation** (`python -m evaluation.run_eval --generation`, 48 questions, Qwen2.5-3B on CPU; report `evaluation/reports/eval_20261114_194441.json`):

| Metric | Result |
|---|---|
| In-scope questions answered (40) | 97.5 % — all with sources: 37 local library, 2 MedlinePlus/FDA live, 1 not answered |
| Claims shown that cite a passage from the labelled source (local answers) | 81.2 % |
| Generated claims passing citation + safety validation | 67.4 % (the rest are removed before display) |
| Errors | 0 |
| Median time per answer | 58 s (CPU) |
| "Out-of-scope" set (8) | 7 of 8 are **medical questions the local library doesn't cover** (dengue treatment, MRI, PSA test, knee-arthritis exercises, migraine causes, ashwagandha, insulin price). By design they are now answered from MedlinePlus / Wikipedia / labelled general knowledge, so the old "abstention" score (12.5 %) no longer measures refusal. The only non-medical question ("How do airplanes fly?") was declined; browser tests also declined "capital of India" and "hack someone's bank account" |

Evaluation data is synthetic or public only: no real patient data is committed.
