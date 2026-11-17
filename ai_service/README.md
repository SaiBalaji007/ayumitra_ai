# AyuMitra AI service: Advanced Medical RAG

Evidence-grounded medical question answering over trusted, public-domain knowledge.
Pretrained models only; nothing is fine-tuned.

```
question → safety screen → query rewriting / multi-query
        → dense (ChromaDB) ‖ BM25 → Reciprocal Rank Fusion → metadata filter
        → cross-encoder rerank → relevance gate (abstain if nothing relevant)
        → contextual compression (verbatim sentences + offsets) → evidence E1..En
        → Qwen2.5-3B-Instruct (JSON-schema constrained claims, each citing evidence)
        → citation validation (NLI entailment + numbers check) → output safety screen
        → structured answer with numbered citations
```

| Component | Choice |
|---|---|
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (baseline; swap via `AYUMITRA_EMBEDDING_MODEL`) |
| Vector DB | ChromaDB, one collection per **domain × embedding model × schema version** |
| Keyword search | Okapi BM25 (`retrieval/bm25.py`), medical-aware tokenizer |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Claim verification | `cross-encoder/nli-deberta-v3-small` (entailment) |
| LLM | Qwen2.5-3B-Instruct via any OpenAI-compatible server |
| Knowledge store | SQLite (`data/knowledge.sqlite3`): sources, sections (parents), chunks |

## Setup (Windows, CPU)

```powershell
cd ai_service
python -m venv .venv
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\pip install -r requirements.txt
```

LLM runtime (local CPU): the official llama.cpp Windows CPU build in `runtime\llama\` and Qwen's official
4-bit GGUF in `models\` (`qwen2.5-3b-instruct-q4_k_m.gguf`, SHA-256 checked against Hugging Face).
Start it with `powershell -ExecutionPolicy Bypass -File scripts\start_llm.ps1`. It serves on 127.0.0.1:8081.

**GPU deployment:** serve `Qwen/Qwen2.5-3B-Instruct` with vLLM using bitsandbytes 4-bit (NF4) and set
`AYUMITRA_LLM_BASE_URL`. That path is not tested on the development machine, which has no NVIDIA GPU.

## Use

```powershell
.venv\Scripts\python -m ayumitra_ai.cli ingest          # fetch + index sources in knowledge\sources.json
.venv\Scripts\python -m ayumitra_ai.cli stats
.venv\Scripts\python -m ayumitra_ai.cli retrieve "What does a high HbA1c mean?"
.venv\Scripts\python -m ayumitra_ai.cli ask "What does a high HbA1c mean?"
.venv\Scripts\uvicorn ayumitra_ai.api:app --host 127.0.0.1 --port 8001
.venv\Scripts\python -m pytest                          # offline unit tests (fake models)
.venv\Scripts\python -m evaluation.run_eval             # retrieval ablation; add --generation for LLM eval
```

## Rules enforced in code
- Only https sources on the trusted-host allowlist are ingested (`ingestion/loaders.py`). MedlinePlus
  A.D.A.M. encyclopedia and ASHP drug monographs are licensed and excluded.
- Knowledge collections (`kb_*`) never contain patient documents.
- A collection refuses vectors from a different embedding model or dimension.
- With too little relevant evidence, the service abstains without calling the LLM.
- Every displayed sentence is a validated claim citing retrieved evidence. Claims with numbers that
  aren't in the cited passage, diagnoses aimed at the user, or dose instructions are removed.
