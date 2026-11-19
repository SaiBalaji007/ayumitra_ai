"""
Shared fixtures. Test documents use FICTIONAL terms (Zentrox, zentrine, Kelvara) so fixture text
can never be mistaken for medical information. Models are deterministic offline fakes.
"""

from __future__ import annotations

import json
import os

import pytest

# The local vision model takes minutes per image on CPU; unit tests exercise the OCR path. The vision reader
# has its own tests that don't need the model (tests/test_vision_reader.py).
os.environ.setdefault("AYUMITRA_VISION_ENABLED", "false")
os.environ.setdefault("AYUMITRA_NER_ENABLED", "false")  # NER helper is tested with a fake model (test_vision_reader.py)

from ayumitra_ai.config import Settings
from ayumitra_ai.ingestion.pipeline import Ingestor
from ayumitra_ai.models import HashingEmbedder, LexicalEntailment, LexicalReranker
from ayumitra_ai.schemas import Domain, SourceSpec
from ayumitra_ai.store.knowledge_db import KnowledgeDB
from ayumitra_ai.store.vector_store import VectorStore

ZENTROX_HTML = """<html><head><title>Zentrox Test</title></head><body>
<nav>Home | Menu | Search</nav>
<div id="content">
<h1>Zentrox Test</h1>
<h2>What is a Zentrox test?</h2>
<p>A Zentrox test measures the amount of zentrine in your blood. Zentrine is a fictional protein used only in software tests.</p>
<h2>What is it used for?</h2>
<p>The test is used to check for Kelvara syndrome, a fictional condition.</p>
<ul><li>It may be part of a routine checkup.</li><li>It may be ordered if you have tiredness.</li></ul>
<h2>What do the results mean?</h2>
<p>A zentrine level above 42 units may mean Kelvara syndrome. A normal level is between 10 and 40 units.</p>
<p>Your provider will explain what your results mean.</p>
<h2>References</h2>
<p>Example reference that must be skipped.</p>
</div>
<footer>Page last updated: Last updated March 3, 2025</footer>
</body></html>"""

QUORVIN_HTML = """<html><body><div id="content">
<h1>Quorvin Panel</h1>
<h2>What is a Quorvin panel?</h2>
<p>A Quorvin panel is a group of fictional tests that measure plinth minerals in urine.</p>
<h2>Why do I need it?</h2>
<p>You may need a Quorvin panel if you have fictional plinth stones.</p>
</div></body></html>"""


class FakeLLM:
    """Returns a scripted JSON answer. `claims_fn(evidence_text)` builds the claims."""

    model = "test/fake-llm"

    def __init__(self, claims_fn=None):
        self.calls = []
        self.claims_fn = claims_fn

    def complete(self, messages, *, json_schema=None, max_tokens=None, temperature=None):
        self.calls.append(messages)
        user = messages[-1]["content"]
        if self.claims_fn is None:
            return json.dumps({"status": "insufficient_evidence", "claims": []})
        return json.dumps({"status": "answered", "claims": self.claims_fn(user)})

    def health(self):
        return True


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        embedding_model="test/hashing-embedder",
        reranker_model="test/lexical-reranker",
        nli_model="test/lexical-entailment",
        min_rerank_score=-1.0,
        semantic_split_threshold=-1.0,
        external_sources_enabled=False,  # tests never call the internet
        general_knowledge_fallback=False,  # enabled explicitly in its own tests
        wikipedia_contact="",  # never contact Wikipedia from tests
    )


@pytest.fixture
def embedder():
    return HashingEmbedder()


@pytest.fixture
def stores(settings, embedder):
    db = KnowledgeDB(settings.knowledge_db)
    vectors = VectorStore(settings.chroma_dir, embedder)
    return db, vectors


@pytest.fixture
def ingested(settings, embedder, stores):
    db, vectors = stores
    ing = Ingestor(settings, embedder, db, vectors)
    specs = [
        SourceSpec(id="test-zentrox", title="Zentrox Test", url="https://medlineplus.gov/test/zentrox/",
                   domain=Domain.LAB_TESTS, publisher="Test Publisher", license="test", content_selector="#content"),
        SourceSpec(id="test-quorvin", title="Quorvin Panel", url="https://medlineplus.gov/test/quorvin/",
                   domain=Domain.GENERAL, publisher="Test Publisher", license="test", content_selector="#content"),
    ]
    results = [
        ing.ingest(specs[0], content=(ZENTROX_HTML.encode(), "html")),
        ing.ingest(specs[1], content=(QUORVIN_HTML.encode(), "html")),
    ]
    return db, vectors, results


@pytest.fixture
def make_pipeline(settings, embedder, ingested):
    from ayumitra_ai.pipeline import RagPipeline

    db, vectors, _ = ingested

    def _make(llm):
        return RagPipeline(settings, embedder=embedder, reranker=LexicalReranker(), nli=LexicalEntailment(),
                           llm=llm, db=db, vectors=vectors)

    return _make


@pytest.fixture(autouse=True)
def _isolate_chroma():
    """Each test uses its own temporary Chroma directory. Chroma caches one client "system" per
    process; clearing it between tests stops one test's segment cache leaking into the next."""
    yield
    try:
        from chromadb.api.client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except Exception:
        pass
