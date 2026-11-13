# AyuMitra AI

**AI-Powered Medical Intelligence and Personalized Healthcare Platform.**

*Your Health Documents. Understood Intelligently.*

AyuMitra AI understands medical documents, extracts prescriptions, retrieves trusted medical knowledge,
explains laboratory results and generates evidence-supported patient education, built on Advanced RAG.

> **Educational tool, not a medical device.** AyuMitra AI explains documents and retrieves trusted
> references. It does not diagnose, prescribe, or replace a doctor or pharmacist.

## Core systems
1. **Medical Report Intelligence**: lab report extraction, reference intervals, and grounded explanations
2. **Prescription Intelligence**: OCR, medicine normalization, and verified drug information
3. **Evidence-Based Knowledge Assistant**: hybrid RAG with reranking and citation validation

These are supported by longitudinal report comparison, diet and lifestyle education, and an optional GraphRAG layer.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full blueprint and roadmap.

## Repository layout
```
frontend/         React + TypeScript + Vite + Tailwind
backend/          Django + DRF (auth, documents, APIs, Celery tasks)
ai_service/       OCR / NLP / RAG / Qwen inference (separate process, GPU host)
infrastructure/   Docker and deployment config
tests/            Cross-service and evaluation tests
docs/             Architecture and decisions
```

## Local development

### 1. Environment
```bash
cp .env.example .env      # then set DJANGO_SECRET_KEY
```
Generate a secret key with:
`python -c "import secrets; print(secrets.token_urlsafe(50))"`

### Database: SQLite
AyuMitra uses **SQLite**, so there's no database server to install. `python manage.py migrate` creates
`backend/db.sqlite3` (gitignored). To put it somewhere else, set `SQLITE_PATH` in `.env`.

- The database runs in WAL mode with a busy timeout, so the API and a Celery worker can share the file.
- **Backups:** copy `db.sqlite3` together with `backend/private_media/`, since the files and their rows belong together.
  Use `sqlite3 db.sqlite3 ".backup backup.sqlite3"` (or stop the server first) rather than copying a live file.
- **Reset:** delete `db.sqlite3` and `private_media/`, then run `migrate` again.
- Tests run against a separate in-memory SQLite database and never touch your data.

### 2. Backend
```bash
cd backend
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver      # http://localhost:8000/api/health/
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

### Full stack with Docker
```bash
docker compose up --build       # redis, backend, celery worker, frontend (SQLite on the `appdata` volume)
```

## Roadmap status
- [x] Phase 1: Architecture and repository setup
- [x] Phase 2: Premium frontend (landing, auth, dashboard shell, light/dark themes)
- [ ] Phase 3: Backend foundation
- [ ] Phases 4–13: see docs/ARCHITECTURE.md
