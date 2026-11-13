# AyuMitra AI: Architecture Blueprint

> AyuMitra AI – AI-Powered Medical Intelligence and Personalized Healthcare Platform.
> *Your Health Documents. Understood Intelligently.*

## Brand
Midnight navy `--navy` · teal `--teal` / `--primary` · mint `--mint` · white · soft violet `--violet`.
Tokens live in `frontend/src/index.css`; components only use semantic token names.

## Layers
| Layer | Responsibility |
|---|---|
| Frontend (React + TS) | User experience: landing, dashboard, upload, prescriptions, chat, timeline, exports |
| Django REST API | Auth (JWT), users, documents, conversations, permissions, orchestration |
| Application services | SQLite (records), private file storage, Celery + Redis (long jobs) |
| AI service | OCR (PaddleOCR + Tesseract), NLP (spaCy/scispaCy), RAG (LangChain + LangGraph), ChromaDB |
| Inference | Qwen2.5-3B-Instruct, 4-bit NF4, on a dedicated GPU host |

Django never runs models in-process. Long work (OCR, analysis) goes through Celery, which calls the AI service.

## Technology choices
React + TS + Vite · Tailwind + shadcn/ui · Framer Motion · Recharts · Axios + React Query ·
Django + DRF · SQLite · JWT · Celery + Redis · Qwen2.5-3B-Instruct (NF4) · all-MiniLM-L6-v2 (baseline) ·
ChromaDB · BM25 · LangChain + LangGraph · cross-encoder reranker · PaddleOCR + Tesseract · PyMuPDF ·
spaCy + scispaCy · RxNorm.

All model choices are configurable through env vars (see `.env.example`). Benchmark biomedical embedding models
against MiniLM before switching. Qwen2.5-3B is an initial inference model and is **not medically validated**.

## Engines
**A. Report intelligence:** PyMuPDF → OCR for scans → table/layout → NER → parameter, unit and reference-interval
extraction → lab flag (as printed) → RAG → Qwen explanation → safety validation.
Always preserve the lab's own reference interval and keep the lab's flag separate from the system's interpretation.

**B. Prescription intelligence:** OCR → field extraction (medicine, strength, dose, frequency, timing, duration,
food instructions) with field-level confidence → RxNorm normalization → verified drug information.
Rules: never guess unclear handwriting; never generate a missing dose or duration; never prescribe; require user
confirmation of uncertain fields; "no interaction found" ≠ "no interaction exists".

**C. Advanced RAG:** intent classification → query rewrite / multi-query → dense + BM25 in parallel → RRF →
metadata filter → cross-encoder rerank → contextual compression → evidence assembly → Qwen → citation validation →
safety engine → structured JSON. Parent-child chunking; GraphRAG is optional.

## Knowledge base
Candidate sources: MedlinePlus, PubMed, WHO, DailyMed, RxNorm, and verified Indian references. Check each source's
licence/terms before ingestion. Store source, version, publication date, page and ingestion date per chunk.
Collections are split by domain (general, lab tests, medicines, nutrition, lifestyle, guidelines) and by embedding
model version.

## Data isolation
Private patient documents are never in the shared knowledge collections. Every retrieval over personal data is
filtered by owner at the query layer and enforced again in the API permission layer.

## Database entities (SQLite)
SQLite is the project database. It needs no server, the schema is plain Django models, and WAL mode
handles the API and worker sharing the file. Its limit is one writer at a time, which suits this
project's scale. If many concurrent users ever need it, moving to a server database is a settings
change plus a data migration; no model changes are needed.

User · PatientProfile · MedicalDocument · DocumentPage · ExtractedReport · LabParameter · Prescription ·
PrescriptionMedicine · MedicineReference · MedicalFinding · Recommendation · KnowledgeSource · Conversation ·
ChatMessage · ProcessingTask · AuditLog

## Roadmap
1. Architecture and repo setup ✅
2. ✅ Premium frontend: design system, landing, auth pages, dashboard, navigation, light/dark
3. Backend foundation: DRF APIs, JWT, models, permissions, file storage
4. Document processing: PDF, OCR, layout, classification, structured extraction
5. Medical NLP: NER, medicines, lab entities, unit normalization, confidence
6. Knowledge ingestion: chunking, metadata, embeddings, ChromaDB
7. Advanced RAG: dense, BM25, RRF, rewriting, reranking, compression, citations
8. LLM + LangGraph: Qwen, intent routing, conditional workflows, JSON output, safety
9. Prescription intelligence
10. Report intelligence + report-specific chat
11. Timeline, comparison, diet/lifestyle education, PDF exports
12. Testing and security: unit/integration, RAG eval, OCR eval, permissions, safety, performance
13. Production: Docker, cloud, persistent storage, GPU inference, HTTPS, monitoring, backups

## Deployment
Frontend on Vercel. Django on Render or Azure, with SQLite on a persistent disk (one app instance writes to it) and managed Redis. ChromaDB on persistent disk (or a managed
vector DB). Qwen on a separate GPU provider, since a normal Render web service can't host it. Encrypted private
storage with retention and deletion policies. Review DPDP Act obligations for health data.

## Evaluation
Recall@K, Precision@K, MRR, NDCG (retrieval) · faithfulness, citation accuracy (generation) ·
character- and field-level accuracy (OCR) · field precision/recall (prescriptions) · latency.
Build a small, medically reviewed eval set: printed reports, scans, handwritten prescriptions, ambiguous cases.
