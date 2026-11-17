"""All tunables in one place, overridable with AYUMITRA_* environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AYUMITRA_", env_file=SERVICE_ROOT / ".env", extra="ignore")

    # --- storage ---
    data_dir: Path = SERVICE_ROOT / "data"
    sources_manifest: Path = SERVICE_ROOT / "knowledge" / "sources.json"

    # --- models (pretrained only; no fine-tuning anywhere) ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_query_prefix: str = ""     # e.g. "query: " for e5 models
    embedding_passage_prefix: str = ""   # e.g. "passage: "
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    nli_model: str = "cross-encoder/nli-deberta-v3-small"
    device: str = "cpu"

    # --- LLM (any OpenAI-compatible server: llama.cpp llama-server, vLLM, ...) ---
    llm_base_url: str = "http://127.0.0.1:8081/v1"
    llm_model: str = "qwen2.5-3b-instruct"
    llm_api_key: str = "not-needed-for-local"
    llm_timeout_s: float = 240.0
    llm_max_tokens: int = 1200  # room for a sectioned answer (up to 8 claims with quotes)
    llm_temperature: float = 0.1
    use_llm_query_rewrite: bool = False  # adds an LLM call per question; off by default on CPU

    # --- chunking ---
    chunk_target_words: int = 140
    chunk_max_words: int = 220
    chunk_overlap_sentences: int = 1
    semantic_split_threshold: float = 0.25  # split where adjacent-sentence cosine falls below
    parent_max_words: int = 600

    # --- retrieval ---
    dense_k: int = 30
    bm25_k: int = 30
    rrf_k: int = 60
    fused_k: int = 25
    rerank_k: int = 6
    # Live fallback to MedlinePlus (NLM) and openFDA drug labels when the local knowledge base has no answer.
    external_sources_enabled: bool = True
    # Last resort for health questions no source covers: Qwen's general knowledge, clearly labelled as
    # unverified, safety-filtered, never with links. Non-health questions are still declined.
    general_knowledge_fallback: bool = True
    # Wikipedia requires a contact (URL or email) in the User-Agent. Empty = Wikipedia not used.
    # Used only for questions confirmed to be about health, after the official sources.
    wikipedia_contact: str = ""
    min_rerank_score: float = -4.0   # below this, the best passage is not considered relevant
    max_queries: int = 4

    # --- evidence and validation ---
    compression_max_sentences: int = 5
    evidence_max_words: int = 900
    nli_entailment_threshold: float = 0.5
    lexical_support_threshold: float = 0.6

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def knowledge_db(self) -> Path:
        return self.data_dir / "knowledge.sqlite3"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()
