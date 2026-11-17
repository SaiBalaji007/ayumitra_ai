"""
End-to-end grounded answering:

  question -> safety screen -> query rewriting / multi-query -> hybrid retrieval (dense + BM25, RRF,
  metadata filter) -> cross-encoder rerank -> relevance gate -> contextual compression ->
  evidence assembly -> Qwen (JSON schema, sectioned claims) -> citation validation (NLI + numbers) ->
  output safety screen -> structured answer

If the local knowledge base yields no verified claim, the same steps run on passages fetched live from
external trusted sources (MedlinePlus health topics, FDA drug labels; see external.py). Nothing is ever
answered without a passage that supports it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime

from .citations import CitationValidator, _quote_in_evidence, garbled_terms, lexical_support
from .config import Settings, get_settings
from .evidence import assemble_evidence
from .external import ExternalSources
from .generation import generate_claims
from .ingestion.chunking import chunk_section
from .llm.client import LLMClient, LLMError
from .models import load_embedder, load_nli, load_reranker
from .retrieval.hybrid import HybridRetriever, RetrievalConfig
from .retrieval.query import build_queries, expand_abbreviations, strip_filler
from .safety import screen_claim, screen_question
from .schemas import (
    AnswerStatus,
    Citation,
    Domain,
    Evidence,
    RagAnswer,
    RetrievedChunk,
    Section,
    SourceRecord,
    ValidatedClaim,
)
from .store.knowledge_db import KnowledgeDB
from .store.vector_store import VectorStore

log = logging.getLogger(__name__)

NO_EVIDENCE_MESSAGE = (
    "I searched AyuMitra's medical library and external sources (MedlinePlus, MeSH, FDA drug labels and Wikipedia) "
    "but didn't find information that answers this reliably, so I won't guess. Try naming the test, "
    "condition or medicine (for example \"What does a high TSH mean?\"), or ask your doctor."
)

SECTION_TITLES = {
    "direct_answer": "Direct answer",
    "explanation": "Detailed explanation",
    "key_points": "Important points",
    "see_doctor": "When to consult a doctor",
}
GENERAL_DOCTOR_ADVICE = (
    "General advice: talk to a doctor if you have symptoms that worry you or don't go away, if a result on "
    "your report is outside the lab's range, or before starting, stopping or changing any medicine or supplement."
)

UNVERIFIED_NOTICE = (
    "No trusted medical source in AyuMitra's library, MedlinePlus, MeSH, FDA labels or Wikipedia covered this question, so "
    "this explanation comes from the AI model's general medical knowledge. It was not checked against a source: "
    "treat it as general information and confirm with a doctor."
)

HEALTH_CHECK_SCHEMA = {"type": "object", "properties": {"health": {"type": "boolean"}}, "required": ["health"]}
HEALTH_CHECK_PROMPT = (
    "Decide if the user's message is a question about health or medicine: the human body, diseases, symptoms, "
    "medical tests or lab results, medicines, medical procedures, vitamins, nutrition, diet, fitness, sleep or "
    "mental health. Answer with JSON {\"health\": true} or {\"health\": false}. Anything else (geography, "
    "computers, money, crime, sport, general knowledge) is false."
)
GENERAL_ANSWER_PROMPT = """You are AyuMitra, a careful health-education assistant for patients in India.
No trusted source was found for this question, so answer from well-established general medical knowledge.
Rules:
- Use exactly these four headings, each on its own line: "### Direct answer", "### Detailed explanation",
  "### Important points", "### When to consult a doctor". Use "- " bullets under the last two.
- Short sentences in simple English; explain medical words. At most 220 words.
- Only state well-established facts. If something varies between people or is uncertain, say so.
- Never give medicine doses, never tell the user to start, stop or change a medicine, never diagnose the user.
- Do not include links, references or source names.
- If the question describes an emergency (chest pain, trouble breathing, stroke signs, heavy bleeding,
  thoughts of self-harm), tell them to call 112 immediately."""
_SECTION_HEADINGS = ("### Direct answer", "### Detailed explanation", "### Important points", "### When to consult a doctor")
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)

# Common nutrients/lab analytes that are also RxNorm "ingredients": don't fetch drug labels for them.
_NOT_MEDICINE_WORDS = {
    "iron", "calcium", "sodium", "potassium", "magnesium", "zinc", "water", "oxygen", "glucose", "cholesterol",
    "protein", "vitamin", "folate", "insulin", "hemoglobin", "creatinine", "urea", "albumin", "bilirubin",
    "sugar", "salt", "fiber", "fibre", "caffeine", "alcohol", "banana", "bananas", "tocopherol",
}


_FRAGMENT_REF = re.compile(r"\b(table|figure|fig\.|section|appendix)\s*\d", re.I)


def malformed_claim(text: str) -> str | None:
    """Claims shown to patients must be complete, self-contained sentences. Rejects copied fragments such
    as '... and more common than in placebo-treated patients, are listed in Table 1.'"""
    t = text.strip()
    if not t or t.startswith(("...", "\u2026", "(", "-", ",", ";")) or not t[0].isalnum() or t[0].islower():
        return "not a complete sentence"
    if _FRAGMENT_REF.search(t):
        return "refers to a table or section the reader cannot see"
    if len(t.split()) < 4:
        return "too short to be informative"
    return None


def drop_near_duplicates(claims: list[ValidatedClaim], threshold: float = 0.8) -> list[ValidatedClaim]:
    """Small models often restate the same fact in other words; keep the first, drop a restatement when
    >= threshold of either claim's content words are contained in the other."""
    from .text import content_terms

    kept, seen = [], []
    for c in claims:
        terms = content_terms(c.text)
        if any(terms and t and len(terms & t) / min(len(terms), len(t)) >= threshold for t in seen):
            continue
        kept.append(c)
        seen.append(terms)
    return kept


def _render_answer(claims: list[ValidatedClaim], id_to_n: dict[str, int]) -> str:
    """Sectioned plain text: '### Heading' lines, then sentences ('- ' bullets for lists) with [n] marks."""
    by_section: dict[str, list[str]] = {k: [] for k in SECTION_TITLES}
    for c in claims:
        marks = "".join(f"[{id_to_n[e]}]" for e in dict.fromkeys(c.evidence_ids) if e in id_to_n)
        text = c.text.rstrip()
        by_section.setdefault(c.section, []).append(f"{text}{'' if text.endswith(('.', '!', '?')) else '.'} {marks}".strip())
    if not by_section["direct_answer"]:  # the model skipped it: the first claim answers directly
        first = next(k for k in ("explanation", "key_points", "see_doctor") if by_section[k])
        by_section["direct_answer"].append(by_section[first].pop(0))
    if not by_section["see_doctor"]:
        by_section["see_doctor"].append(GENERAL_DOCTOR_ADVICE)
    out = []
    for key, title in SECTION_TITLES.items():
        lines = by_section[key]
        if not lines:
            continue
        out.append(f"### {title}")
        bullet = key in ("key_points", "see_doctor") and len(lines) > 1
        out.extend(f"- {line}" if bullet else line for line in lines)
    return "\n".join(out)


class RagPipeline:
    def __init__(self, settings: Settings | None = None, *, embedder=None, reranker=None, nli=None, llm=None,
                 db: KnowledgeDB | None = None, vectors: VectorStore | None = None, external: ExternalSources | None = None):
        self.s = settings or get_settings()
        s = self.s
        self.embedder = embedder or load_embedder(s.embedding_model, s.device, s.embedding_query_prefix, s.embedding_passage_prefix)
        self.reranker = reranker if reranker is not None else load_reranker(s.reranker_model, s.device)
        self.nli = nli if nli is not None else load_nli(s.nli_model, s.device)
        self.llm = llm or LLMClient(s.llm_base_url, s.llm_model, s.llm_api_key, s.llm_timeout_s, s.llm_temperature, s.llm_max_tokens)
        self.db = db or KnowledgeDB(s.knowledge_db)
        self.vectors = vectors or VectorStore(s.chroma_dir, self.embedder)
        self.retriever = HybridRetriever(self.db, self.vectors, self.embedder, self.reranker)
        self.validator = CitationValidator(self.nli, entail_threshold=s.nli_entailment_threshold,
                                           lexical_threshold=s.lexical_support_threshold)
        self.external = external if external is not None else ExternalSources(
            s.data_dir / "external_cache", enabled=s.external_sources_enabled, wikipedia_contact=s.wikipedia_contact)
        self._health_cache: dict[str, bool] = {}

    def retrieval_config(self, **overrides) -> RetrievalConfig:
        s = self.s
        cfg = RetrievalConfig(dense_k=s.dense_k, bm25_k=s.bm25_k, rrf_k=s.rrf_k, fused_k=s.fused_k, rerank_k=s.rerank_k)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    @staticmethod
    def _rerank_query(question: str) -> str:
        # Rerank (and compress) against the question with abbreviations/synonyms expanded: "TOCOPHEROL"
        # alone scores low against a passage that says "vitamin E"; "TOCOPHEROL (vitamin E)" doesn't.
        return expand_abbreviations(strip_filler(question)) or question

    def retrieve_evidence(self, question: str, *, domains: list[Domain] | None = None, use_llm_rewrite: bool | None = None,
                          cfg: RetrievalConfig | None = None) -> tuple[list[Evidence], list[str], dict, bool]:
        use_llm = self.s.use_llm_query_rewrite if use_llm_rewrite is None else use_llm_rewrite
        queries = build_queries(question, llm=self.llm, use_llm=use_llm, max_queries=self.s.max_queries)
        rerank_q = self._rerank_query(question)
        results, trace = self.retriever.retrieve(queries, domains=domains, cfg=cfg or self.retrieval_config(),
                                                 rerank_query=rerank_q)
        relevant = bool(results) and (results[0].rerank_score is None or results[0].rerank_score >= self.s.min_rerank_score)
        if results and results[0].rerank_score is not None:
            results = [r for r in results if r.rerank_score >= self.s.min_rerank_score]
        evidence = assemble_evidence(rerank_q, results, self.reranker, max_sentences=self.s.compression_max_sentences,
                                     max_words=self.s.evidence_max_words) if relevant else []
        return evidence, queries, trace.timings_ms, relevant

    # ------------------------------------------------------------------ external fallback
    def _medicines_in(self, question: str) -> list[str]:
        """Exact RxNorm ingredient names in the question (no fuzzy guessing), for FDA label lookup."""
        try:
            from .nlp.medicines import _key, default_lexicon

            lex = default_lexicon()
        except Exception:  # lexicon not downloaded: MedlinePlus search still works
            return []
        found = []
        for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", question):
            k = _key(w)
            if k not in _NOT_MEDICINE_WORDS and k in lex.ingredients:
                found.append(lex.ingredients[k][1].lower())
        return found

    def external_evidence(self, question: str) -> list[Evidence]:
        if not self.s.external_sources_enabled or self.external is None:
            return []
        return self._evidence_from_docs(question, self.external.search(question, medicines=self._medicines_in(question)))

    def _evidence_from_docs(self, question: str, docs) -> list[Evidence]:
        if not docs:
            return []
        now = datetime.now(UTC).isoformat(timespec="seconds")
        items: list[RetrievedChunk] = []
        for d in docs:
            src = SourceRecord(id=d.id, title=d.title, url=d.url, domain=Domain.GENERAL, publisher=d.publisher,
                               license="Public domain (U.S. government)", published_date=d.published_date,
                               ingested_at=now, checksum="")
            sec = Section(id=f"{d.id}#s0", source_id=d.id, heading_path=[d.title], text=d.text, page=None, order=0)
            for ch in chunk_section(sec, domain=Domain.GENERAL, title=d.title, target_words=self.s.chunk_target_words,
                                    max_words=self.s.chunk_max_words, overlap_sentences=self.s.chunk_overlap_sentences):
                items.append(RetrievedChunk(chunk=ch, source=src))
        if not items:
            return []
        rerank_q = self._rerank_query(question)
        for it, score in zip(items, self.reranker.score(rerank_q, [i.chunk.embed_text for i in items]), strict=True):
            it.rerank_score = float(score)
        items = sorted((i for i in items if i.rerank_score >= self.s.min_rerank_score), key=lambda i: -i.rerank_score)
        return assemble_evidence(rerank_q, items[: self.s.rerank_k], self.reranker,
                                 max_sentences=self.s.compression_max_sentences, max_words=self.s.evidence_max_words)

    # ------------------------------------------------------------------ last resort: general knowledge
    def is_health_question(self, question: str) -> bool:
        """Qwen yes/no: is this about health? Used only when no official source matched, to keep non-health
        questions ("capital of India", "hack a bank account") away from Wikipedia and general knowledge."""
        key = question.strip().lower()
        if key in self._health_cache:
            return self._health_cache[key]
        self._health_cache[key] = result = self._ask_health(question)
        return result

    def _ask_health(self, question: str) -> bool:
        try:
            raw = self.llm.complete([{"role": "system", "content": HEALTH_CHECK_PROMPT},
                                     {"role": "user", "content": question[:500]}],
                                    json_schema=HEALTH_CHECK_SCHEMA, max_tokens=20, temperature=0)
            return json.loads(raw).get("health") is True
        except (LLMError, ValueError):
            return False

    def general_knowledge_answer(self, question: str, *, medication_q: bool) -> str | None:
        """Unverified explanation from the model's own knowledge, filtered sentence by sentence through
        the same output safety screen. Returns None if nothing safe and well-formed remains."""
        raw = self.llm.complete([{"role": "system", "content": GENERAL_ANSWER_PROMPT},
                                 {"role": "user", "content": expand_abbreviations(question)}], max_tokens=600)
        out, have_direct, section = [], False, None
        for line in raw.splitlines():
            line = _URL.sub("", line).strip().strip("*").strip()
            if not line:
                continue
            heading = next((h for h in _SECTION_HEADINGS if line.lstrip("#").strip().lower() == h[4:].lower()), None)
            if heading:
                section = heading
                out.append(heading)
                continue
            if section is None:  # text before the first heading is the direct answer
                section = _SECTION_HEADINGS[0]
                out.append(section)
            body = line[2:] if line.startswith(("- ", "* ")) else line
            if screen_claim(body, "", medication_question=medication_q):
                continue  # drops dose instructions, medicine changes, diagnoses of the user
            out.append(f"- {body}" if line.startswith(("- ", "* ")) else body)
            have_direct |= section == _SECTION_HEADINGS[0]
        # remove headings left without content
        cleaned = [l for i, l in enumerate(out) if not (l.startswith("### ") and (i + 1 == len(out) or out[i + 1].startswith("### ")))]
        return "\n".join(cleaned) if have_direct else None

    def wikipedia_evidence(self, question: str) -> list[Evidence]:
        """Wikipedia passages through the same relevance gate and compression as other external text."""
        if not self.s.external_sources_enabled or self.external is None or not self.s.wikipedia_contact:
            return []
        return self._evidence_from_docs(question, self.external.wikipedia(question))

    # ------------------------------------------------------------------ generation + validation
    def _generate_and_validate(self, question: str, evidence: list[Evidence], medication_q: bool):
        # The model sees the synonym/abbreviation expansion used for search; claims are still validated
        # against the evidence only.
        try:
            _status, claims, _raw = generate_claims(self.llm, expand_abbreviations(question), evidence)
        except ValueError as exc:  # unparseable model output: try the next source instead of failing
            log.warning("Unusable model output, treating as no claims: %s", exc)
            claims = []
        by_id = {e.id: e for e in evidence}
        accepted: list[ValidatedClaim] = []
        rejected: list[ValidatedClaim] = []
        seen: set[str] = set()
        for claim in claims:
            key = re.sub(r"\W+", " ", claim.text.lower()).strip()
            problem = malformed_claim(claim.text) or ("repeats an earlier sentence" if key in seen else None)
            seen.add(key)
            if problem:
                rejected.append(ValidatedClaim(**claim.model_dump(), supported=False, support_score=0.0,
                                               method="quality", reason=problem))
                continue
            v = self.validator.validate(claim, by_id)
            if v.supported:
                cited_text = " ".join(by_id[i].text for i in v.evidence_ids if i in by_id)
                reason = screen_claim(v.text, cited_text, medication_question=medication_q)
                garbled = garbled_terms(v.text, f"{question} {cited_text}")
                if garbled and not reason:
                    reason = f"misspelled term not in the question or sources: {', '.join(garbled)}"
                if reason:
                    v = v.model_copy(update={"supported": False, "reason": f"safety: {reason}"})
            (accepted if v.supported else rejected).append(v)
        return accepted, rejected, by_id

    def answer(self, question: str, *, domains: list[Domain] | None = None) -> RagAnswer:
        t0 = time.perf_counter()
        question = question.strip()
        safety = screen_question(question)
        medication_q = "medication_decision" in safety.flags
        models = {"embedding": self.embedder.model_id, "reranker": getattr(self.reranker, "model_id", "none"),
                  "nli": getattr(self.nli, "model_id", "none"), "llm": getattr(self.llm, "model", "none")}

        evidence, queries, timings, _relevant = self.retrieve_evidence(question, domains=domains)
        timings = dict(timings)
        timings["retrieval_total"] = round((time.perf_counter() - t0) * 1000, 1)
        base = dict(question=question, safety=safety, queries=queries, model=models)

        accepted: list[ValidatedClaim] = []
        rejected: list[ValidatedClaim] = []
        by_id: dict[str, Evidence] = {}
        try:
            if evidence:  # 1st priority: the local knowledge base
                t = time.perf_counter()
                accepted, rejected, by_id = self._generate_and_validate(question, evidence, medication_q)
                timings["generation_local"] = round((time.perf_counter() - t) * 1000, 1)
            if not accepted:  # 2nd priority: external trusted sources, fetched live
                t = time.perf_counter()
                ext = self.external_evidence(question)
                timings["external_retrieval"] = round((time.perf_counter() - t) * 1000, 1)
                if ext:
                    t = time.perf_counter()
                    ext_accepted, ext_rejected, ext_by_id = self._generate_and_validate(question, ext, medication_q)
                    timings["generation_external"] = round((time.perf_counter() - t) * 1000, 1)
                    rejected += ext_rejected
                    if ext_accepted:
                        accepted, by_id = ext_accepted, ext_by_id
                        safety.flags.append("external_sources")
            if not accepted and self.s.wikipedia_contact and self.is_health_question(question):
                # 3rd priority: Wikipedia, for health questions the official sources didn't cover.
                t = time.perf_counter()
                wiki = self.wikipedia_evidence(question)
                timings["wikipedia_retrieval"] = round((time.perf_counter() - t) * 1000, 1)
                if wiki:
                    t = time.perf_counter()
                    w_accepted, w_rejected, w_by_id = self._generate_and_validate(question, wiki, medication_q)
                    timings["generation_wikipedia"] = round((time.perf_counter() - t) * 1000, 1)
                    rejected += w_rejected
                    if w_accepted:
                        accepted, by_id = w_accepted, w_by_id
                        safety.flags.append("wikipedia")
        except (LLMError, ValueError) as exc:
            log.warning("Generation failed: %s", exc)
            raise

        if rejected:
            safety.flags.append(f"rejected_claims:{len(rejected)}")
        timings["total"] = round((time.perf_counter() - t0) * 1000, 1)

        if not accepted and self.s.general_knowledge_fallback and not medication_q:
            t = time.perf_counter()
            text = self.general_knowledge_answer(question, medication_q=medication_q) if self.is_health_question(question) else None
            timings["general_knowledge"] = round((time.perf_counter() - t) * 1000, 1)
            if text:
                safety.flags.append("unverified_general_knowledge")
                safety.notices.insert(0, UNVERIFIED_NOTICE)
                timings["total"] = round((time.perf_counter() - t0) * 1000, 1)
                return RagAnswer(**base, status=AnswerStatus.ANSWERED, answer=text, rejected_claims=rejected,
                                 timings_ms=timings)

        if not accepted:
            return RagAnswer(**base, status=AnswerStatus.INSUFFICIENT_EVIDENCE, answer=NO_EVIDENCE_MESSAGE,
                             rejected_claims=rejected, timings_ms=timings)

        accepted = drop_near_duplicates(accepted)
        # Number citations in order of first use; include only evidence that a validated claim cites.
        id_to_n: dict[str, int] = {}
        for c in accepted:
            for e in c.evidence_ids:
                if e in by_id and e not in id_to_n:
                    id_to_n[e] = len(id_to_n) + 1
        citations = []
        for eid, n in id_to_n.items():
            ev = by_id[eid]
            citing = [c for c in accepted if eid in c.evidence_ids]
            # Show the model's quote if it really occurs in this passage; otherwise the passage sentence that
            # best supports the claims citing it (never an unrelated first sentence).
            quote = next((c.quote for c in citing if c.quote and _quote_in_evidence(c.quote, [ev]) is not None), None)
            if not quote:
                claim_text = " ".join(c.text for c in citing)
                quote = max((s.text for s in ev.sentences), key=lambda s: lexical_support(claim_text, s), default=ev.text)
            citations.append(Citation(id=str(n), title=ev.title, url=ev.url, section=ev.section, page=ev.page,
                                      published_date=ev.published_date, quote=quote, publisher=ev.publisher,
                                      external=ev.external))
        return RagAnswer(**base, status=AnswerStatus.ANSWERED, answer=_render_answer(accepted, id_to_n), claims=accepted,
                         rejected_claims=rejected, citations=citations, timings_ms=timings)
