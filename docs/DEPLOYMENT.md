# AyuMitra AI: Deployment

> Status: the configuration below is **written but not run-tested**. The development machine has
> neither Docker nor an NVIDIA GPU. Everything else in this repository is tested locally on
> Windows/CPU (see `docs/STATUS.md`).

## Topology

```
Browser ── HTTPS ──> reverse proxy (Caddy / nginx / platform TLS)
                       ├── /        frontend (static React build, nginx)
                       └── /api/    backend  (Django + DRF, gunicorn)
                                      ├── SQLite db.sqlite3 + private documents   [volume: appdata]
                                      ├── Redis + Celery worker (document jobs)
                                      └── ai_service (FastAPI; internal only, token-protected)
                                            ├── knowledge.sqlite3 + ChromaDB      [volume: aidata]
                                            └── LLM server: llama.cpp (CPU) or vLLM (GPU)
```

Only the reverse proxy is public. `ai_service`, `llm`, `redis` and the worker sit on the private
network. The AI service never stores patient documents: it analyses bytes in memory and returns
structure.

## 1. Configuration

```bash
cp .env.example .env
```
Set at least:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | 50+ random characters. Startup refuses weak keys when `DEBUG=False` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | your domain, e.g. `ayumitra.example.in` |
| `CSRF_TRUSTED_ORIGINS` / `CORS_ALLOWED_ORIGINS` | `https://ayumitra.example.in` |
| `AI_SERVICE_TOKEN` | random string, shared by backend and ai_service |
| `DOCUMENT_PROCESSING_ENABLED` | `True` |

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(50))"`. Never commit `.env`.

## 2. Models (one time)

```bash
# Qwen2.5-3B-Instruct, official 4-bit GGUF (CPU path), ~2.1 GB
curl -L -o ai_service/models/qwen2.5-3b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf
sha256sum ai_service/models/qwen2.5-3b-instruct-q4_k_m.gguf   # compare with the Hugging Face file page
```
Embedding, reranker, NLI and NER models download automatically into the `aidata` volume on first use.

## 3. Start

```bash
docker compose up -d --build
docker compose exec ai_service python -m ayumitra_ai.cli ingest     # build the knowledge base
docker compose exec ai_service python -m ayumitra_ai.cli rxnorm     # RxNorm lexicon for medicines
docker compose exec backend python manage.py createsuperuser
```

## 4. HTTPS

Put TLS in front of the `frontend` container (port 8080). The simplest option is Caddy, which
issues certificates automatically:
```
ayumitra.example.in {
    reverse_proxy frontend:80
}
```
Django trusts `X-Forwarded-Proto` from the proxy (`SECURE_PROXY_SSL_HEADER`) and, with `DEBUG=False`,
enforces HTTPS redirects, HSTS (1 year) and secure cookies. HSTS preload is deliberately off; turn it on
only once the domain is committed to HTTPS permanently.

## 5. GPU inference (production)

A normal web host can't run the LLM efficiently. Run Qwen on a GPU machine with vLLM using
bitsandbytes 4-bit (NF4) quantisation, then point the AI service at it:

```bash
vllm serve Qwen/Qwen2.5-3B-Instruct --quantization bitsandbytes --max-model-len 8192 \
     --served-model-name qwen2.5-3b-instruct --api-key "$LLM_API_KEY"
```
```
AYUMITRA_LLM_BASE_URL=https://<gpu-host>:8000/v1
AYUMITRA_LLM_API_KEY=<same key>
```
The client code is unchanged: both llama.cpp and vLLM speak the OpenAI-compatible API with
JSON-schema-constrained output. **Untested here (no NVIDIA GPU on the dev machine).** Re-run
`python -m evaluation.run_eval --generation` after switching, and compare the metrics.

## 6. Persistent storage and backups

| Volume | Contents | Backup |
|---|---|---|
| `appdata` | `db/db.sqlite3` (users, records), `media/` (private medical documents) | **Required** |
| `aidata` | knowledge DB, ChromaDB, lexicons, model cache | Optional: rebuildable with `cli ingest` |

SQLite must be copied consistently while the app runs:
```bash
docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('/data/db/db.sqlite3'); d=sqlite3.connect('/data/db/backup.sqlite3'); s.backup(d); d.close()"
docker run --rm -v ayumitra_appdata:/data -v "$PWD/backups:/out" alpine \
  tar czf /out/appdata-$(date +%F).tgz -C /data db/backup.sqlite3 media
```
Encrypt backups at rest (they contain health data), keep them off-host, and test restores.
SQLite allows one writer at a time; this is fine for one app instance. Scaling the backend
horizontally would need a server database.

## 7. Monitoring and logging

- Health: `GET /api/health/` (backend + DB) and `GET /health` on ai_service (models, index sizes,
  LLM reachability). Docker health checks use these.
- Logs: all services log one line per event to stdout (`docker compose logs -f`). Medical
  content (document text, values, questions) is never logged.
- Audit: security events (`register`, `document.upload/view/delete`, `report.export`, profile
  changes) are in the `AuditLog` table, read-only in Django admin.
- Watch: failed `ProcessingTask` rows, 503s from `/api/assistant/ask/` (LLM down) and worker liveness.

## 8. Privacy and regulatory notes (India)

Health data is sensitive personal data. Before handling real patients, review your obligations
under the Digital Personal Data Protection Act, 2023 (consent, purpose limitation, deletion on
request, breach notification) and any applicable clinical-software rules. AyuMitra is an
educational tool and must not be presented as a diagnostic device.
