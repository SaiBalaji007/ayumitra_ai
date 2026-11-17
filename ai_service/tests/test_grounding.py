"""Citation validation, safety rules and the end-to-end grounded pipeline (with fake models)."""

import json

import pytest

from ayumitra_ai.citations import CitationValidator
from ayumitra_ai.evidence import compress
from ayumitra_ai.generation import parse_generation
from ayumitra_ai.models import LexicalEntailment, LexicalReranker
from ayumitra_ai.safety import screen_claim, screen_question
from ayumitra_ai.schemas import (AnswerStatus, Chunk, Claim, Domain, Evidence, EvidenceSentence, RetrievedChunk,
                                 SourceRecord)

from .conftest import FakeLLM


def _ev(eid, text):
    return Evidence(id=eid, chunk_id=f"c-{eid}", source_id="s", title="T", url=None, section="S", page=None,
                    published_date=None, text=text, sentences=[EvidenceSentence(text=text, start=0, end=len(text))],
                    rerank_score=1.0)


EVIDENCE = {
    "E1": _ev("E1", "A zentrine level above 42 units may mean Kelvara syndrome."),
    "E2": _ev("E2", "A Zentrox test measures the amount of zentrine in your blood."),
}


class TestCitationValidator:
    v = CitationValidator(LexicalEntailment(), entail_threshold=0.8)

    def test_supported_claim_passes(self):
        r = self.v.validate(Claim(text="A zentrine level above 42 units may mean Kelvara syndrome.", evidence_ids=["E1"]), EVIDENCE)
        assert r.supported and r.method == "nli"

    def test_rejects_missing_or_invented_citations(self):
        assert not self.v.validate(Claim(text="Zentrine is measured.", evidence_ids=[]), EVIDENCE).supported
        r = self.v.validate(Claim(text="Zentrine is measured in blood.", evidence_ids=["E9"]), EVIDENCE)
        assert not r.supported and "E9" in r.reason

    def test_rejects_numbers_not_in_cited_evidence(self):
        r = self.v.validate(Claim(text="A zentrine level above 50 units may mean Kelvara syndrome.", evidence_ids=["E1"]), EVIDENCE)
        assert not r.supported and r.method == "numbers" and "50" in r.reason

    def test_rejects_claim_citing_the_wrong_passage(self):
        r = self.v.validate(Claim(text="A zentrine level above 42 units may mean Kelvara syndrome.", evidence_ids=["E2"]), EVIDENCE)
        assert not r.supported

    def test_verbatim_quote_path(self):
        # close_restatement off: this test isolates the quote path (a fake quote must never help).
        strict = CitationValidator(LexicalEntailment(), entail_threshold=1.01, lexical_threshold=0.6,
                                   close_restatement_threshold=1.01)
        claim = Claim(text="The Zentrox test measures zentrine in blood.", evidence_ids=["E2"],
                      quote="A Zentrox test measures the amount of zentrine in your blood")
        r = strict.validate(claim, EVIDENCE)
        assert r.supported and r.method == "verbatim_quote"
        fake_quote = claim.model_copy(update={"quote": "Zentrox cures everything forever and always"})
        assert not strict.validate(fake_quote, EVIDENCE).supported

    def test_lexical_fallback_without_nli(self):
        r = CitationValidator(None).validate(Claim(text="Zentrox test measures zentrine blood", evidence_ids=["E2"]), EVIDENCE)
        assert r.supported and r.method == "lexical"


class TestSafety:
    @pytest.mark.parametrize("q", ["I have chest pain and sweating", "my father can't breathe properly",
                                   "she has slurred speech suddenly", "I took too many tablets"])
    def test_urgent(self, q):
        rep = screen_question(q)
        assert rep.urgent and "112" in rep.urgent_message

    def test_self_harm_gives_helpline(self):
        rep = screen_question("I want to end my life")
        assert rep.urgent and "14416" in rep.urgent_message and "self_harm" in rep.flags

    @pytest.mark.parametrize("q", ["Does high blood pressure raise the risk of stroke?", "What is a normal HbA1c?",
                                   "Why is my hemoglobin low?"])
    def test_no_false_alarms(self, q):
        assert not screen_question(q).urgent

    @pytest.mark.parametrize("q", ["How much metformin should I take?", "Can I stop my insulin?", "what dose of vitamin D"])
    def test_medication_decisions_flagged(self, q):
        assert "medication_decision" in screen_question(q).flags

    def test_claim_rules(self):
        assert screen_claim("You have diabetes.", "", medication_question=False)
        assert screen_claim("Take 500 mg twice daily.", "", medication_question=False)
        assert screen_claim("Take 500 mg twice daily.", "Take 500 mg twice daily.", medication_question=True)
        assert screen_claim("A1C shows average blood sugar.", "", medication_question=False) is None


class TestGenerationParsing:
    def test_parses_and_normalises_ids(self):
        status, claims = parse_generation('```json\n{"status":"answered","claims":[{"text":"x","evidence_ids":["[e1]"],"quote":""}]}\n```')
        assert status == "answered" and claims[0].evidence_ids == ["E1"] and claims[0].quote is None

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_generation("not json at all")


def test_compression_keeps_offsets_and_relevant_sentences():
    text = ("Unrelated sentence one. Unrelated sentence two. A zentrine level above 42 units may mean Kelvara. "
            "Unrelated three. Unrelated four. Unrelated five. Unrelated six.")
    ch = Chunk(id="c", source_id="s", section_id="s#0", domain=Domain.GENERAL, text=text, embed_text=text,
               heading_path=["T"], order=0, word_count=len(text.split()))
    src = SourceRecord(id="s", title="T", url=None, domain=Domain.GENERAL, publisher="p", license="l",
                       ingested_at="2026-01-01", checksum="x")
    sents = compress("high zentrine level Kelvara", RetrievedChunk(chunk=ch, source=src), LexicalReranker(), max_sentences=2)
    assert len(sents) == 2
    assert any("42 units" in s.text for s in sents)
    for s in sents:
        assert text[s.start:s.end] == s.text


class TestPipeline:
    def test_grounded_answer_with_citations_and_rejected_hallucination(self, make_pipeline):
        def claims(prompt):
            eid = next(line.split("]")[0].strip("[") for line in prompt.splitlines()
                       if line.startswith("[E") and "Zentrox" in line)
            return [
                {"text": "A zentrine level above 42 units may mean Kelvara syndrome.", "evidence_ids": [eid],
                 "quote": "A zentrine level above 42 units may mean Kelvara syndrome."},
                {"text": "Zentrine above 99 units needs 500 mg of Kelvamab daily.", "evidence_ids": [eid], "quote": ""},
                {"text": "You have Kelvara syndrome.", "evidence_ids": [eid], "quote": ""},
            ]

        p = make_pipeline(FakeLLM(claims))
        ans = p.answer("What does a high zentrine level mean?")
        assert ans.status == AnswerStatus.ANSWERED
        # Sectioned answer: direct answer first, then (here, since the source has none) general doctor advice.
        assert ans.answer.startswith("### Direct answer\nA zentrine level above 42 units may mean Kelvara syndrome. [1]")
        assert "### When to consult a doctor" in ans.answer
        assert len(ans.claims) == 1 and len(ans.rejected_claims) == 2
        assert ans.citations[0].id == "1" and ans.citations[0].title == "Zentrox Test"
        assert "42 units" in ans.citations[0].quote
        assert "99" not in ans.answer and "Kelvamab" not in ans.answer
        assert any(f.startswith("rejected_claims") for f in ans.safety.flags)
        assert ans.timings_ms["total"] > 0

    def test_unrelated_question_abstains_without_calling_llm(self, make_pipeline, settings):
        llm = FakeLLM(lambda p: [])
        p = make_pipeline(llm)
        p.s.min_rerank_score = 0.0
        ans = p.answer("How do airplanes fly?")
        assert ans.status == AnswerStatus.INSUFFICIENT_EVIDENCE
        assert llm.calls == [] and ans.citations == []

    def test_all_claims_rejected_means_insufficient_evidence(self, make_pipeline):
        p = make_pipeline(FakeLLM(lambda prompt: [{"text": "Zentrine cures colds.", "evidence_ids": ["E1"], "quote": ""}]))
        ans = p.answer("What is a Zentrox test?")
        assert ans.status == AnswerStatus.INSUFFICIENT_EVIDENCE and ans.claims == [] and ans.rejected_claims

    def test_urgent_question_still_carries_urgent_notice(self, make_pipeline):
        p = make_pipeline(FakeLLM(None))
        ans = p.answer("I have chest pain, is it my zentrine level?")
        assert ans.safety.urgent and "112" in ans.safety.urgent_message

    def test_knowledge_collections_never_hold_patient_data(self, ingested):
        _, vectors, _ = ingested
        assert all(c["name"].startswith("kb_") for c in vectors.collections())


def test_compression_keeps_list_items_with_lead_in():
    """Regression: compression kept 'Low zentrine levels may be a sign of:' but dropped the items."""
    from types import SimpleNamespace

    from ayumitra_ai.evidence import compress
    from ayumitra_ai.models import LexicalReranker

    text = ("The lab reports zentrine in units. Results are compared with a range. Ranges vary by lab. "
            "Your provider explains results. Ask about your results. "
            "Low zentrine levels may be a sign of:\n- Blood loss from injury\n- Lack of certain nutrients\n"
            "Zentrine is fictional.")
    item = SimpleNamespace(chunk=SimpleNamespace(text=text))
    kept = " ".join(s.text for s in compress("What do low zentrine levels mean?", item, LexicalReranker(), max_sentences=2))
    assert "Low zentrine levels may be a sign of:" in kept
    assert "Blood loss from injury" in kept and "Lack of certain nutrients" in kept


def test_conditional_you_have_is_not_a_diagnosis():
    from ayumitra_ai.safety import screen_claim

    ok = ["If you have anemia, your blood does not carry enough oxygen.",
          "You may need a white blood count if you have signs of an infection."]
    bad = ["You have diabetes.", "You probably have anemia.", "This means you have kidney disease."]
    assert all(screen_claim(c, "", medication_question=False) is None for c in ok)
    assert all(screen_claim(c, "", medication_question=False) == "states a diagnosis about the user" for c in bad)


class _NeverEntails:
    """Stand-in for a brittle NLI model that scores every claim as unsupported."""

    model_id = "test/never"

    def entailment(self, premise, hypotheses):
        return [0.0 for _ in hypotheses]


def _evidence(text):
    from ayumitra_ai.schemas import Evidence, EvidenceSentence

    return Evidence(id="E1", chunk_id="c", source_id="s", title="t", url=None, section="x", page=None,
                    published_date=None, text=text, sentences=[EvidenceSentence(text=text, start=0, end=len(text))],
                    rerank_score=1.0)


def test_close_restatement_accepted_but_additions_and_negations_rejected():
    from ayumitra_ai.citations import CitationValidator
    from ayumitra_ai.schemas import Claim

    v = CitationValidator(_NeverEntails())
    ev = {"E1": _evidence("A high zentrine level may be a sign of Kelvara syndrome or a reaction to a medicine.")}

    def ok(text):
        return v.validate(Claim(text=text, evidence_ids=["E1"], quote=None), ev).supported

    assert ok("A high zentrine blood level may be a sign of Kelvara syndrome or a reaction to a medicine.")
    assert not ok("A high zentrine level is not a sign of Kelvara syndrome or a reaction to a medicine.")
    assert not ok("A high zentrine level may be a sign of Kelvara syndrome, cancer, leukemia, stress or allergies.")
    assert not ok("A high zentrine level means you need antibiotics.")


def test_garbled_medical_terms_are_detected():
    """Regression: Qwen wrote 'TOcoproil is an antioxidant' for TOCOPHEROL and NLI accepted it."""
    from ayumitra_ai.citations import garbled_terms

    ref = "TOCOPHEROL Vitamin E is an antioxidant. Anemia lowers hemoglobin. Infection raises the white cell count."
    assert garbled_terms("TOcoproil is an antioxidant.", ref) == ["tocoproil"]
    for ok in ("Tocopherol is an antioxidant.", "Anaemia means low haemoglobin.",
               "Infections may raise the white cell count.", "Antioxidants protect cells."):
        assert garbled_terms(ok, ref) == []


def test_external_fallback_answers_when_local_kb_has_nothing(make_pipeline, settings):
    """Local KB has nothing on 'Plinthase'; a (stubbed, offline) external trusted source does."""
    from ayumitra_ai.external import ExternalDoc

    class StubExternal:
        def search(self, question, medicines=()):
            return [ExternalDoc(id="ext-mlp-test", title="Plinthase", url="https://medlineplus.gov/plinthase.html",
                                publisher="National Library of Medicine",
                                text="Plinthase. Also called: Plinthic acid.\nPlinthase is a fictional enzyme used only in software tests.")]

    claim = "Plinthase is a fictional enzyme used only in software tests."
    p = make_pipeline(FakeLLM(lambda prompt: [{"section": "direct_answer", "text": claim, "evidence_ids": ["E1"],
                                              "quote": claim}] if "Plinthase is a fictional" in prompt else []))
    p.s = settings.model_copy(update={"external_sources_enabled": True})
    p.external = StubExternal()
    ans = p.answer("What is plinthase?")
    assert ans.status == AnswerStatus.ANSWERED
    assert ans.citations[0].url == "https://medlineplus.gov/plinthase.html" and ans.citations[0].external
    assert "external_sources" in ans.safety.flags


def test_no_external_when_disabled(make_pipeline):
    p = make_pipeline(FakeLLM(None))
    ans = p.answer("What is plinthase?")
    assert ans.status == AnswerStatus.INSUFFICIENT_EVIDENCE and "external_sources" not in ans.safety.flags


class _GeneralKnowledgeLLM:
    """Fake Qwen for the last-resort tier: health classifier + a free-text answer containing unsafe lines."""

    model = "test/general"

    def __init__(self, health: bool):
        self.health = health
        self.calls = []

    def complete(self, messages, *, json_schema=None, max_tokens=None, temperature=None):
        self.calls.append(messages[0]["content"][:30])
        if json_schema and "health" in json_schema.get("properties", {}):
            return json.dumps({"health": self.health})
        if json_schema:  # grounded generation: nothing to cite
            return json.dumps({"status": "insufficient_evidence", "claims": []})
        return ("### Direct answer\nA plinthectomy is a fictional operation used in software tests.\n"
                "### Detailed explanation\nIt is described at https://example.com/fake-source.\n"
                "Take 500 mg of plinthol twice a day.\n"
                "### Important points\n- Stop taking your medicine before it.\n- Recovery time varies between people.\n"
                "### When to consult a doctor\n- See a doctor if you have pain or fever.")

    def health_check(self):
        return True


def test_general_knowledge_fallback_is_labelled_and_safety_filtered(make_pipeline, settings):
    llm = _GeneralKnowledgeLLM(health=True)
    p = make_pipeline(llm)
    p.s = settings.model_copy(update={"general_knowledge_fallback": True})
    ans = p.answer("What is a plinthectomy?")
    assert ans.status == AnswerStatus.ANSWERED and ans.citations == []
    assert "unverified_general_knowledge" in ans.safety.flags
    assert "not checked against a source" in ans.safety.notices[0]
    assert ans.answer.startswith("### Direct answer\nA plinthectomy is a fictional operation")
    assert "500 mg" not in ans.answer and "Stop taking" not in ans.answer  # unsafe lines removed
    assert "http" not in ans.answer and "example.com" not in ans.answer   # no invented references
    assert "Recovery time varies" in ans.answer and "### When to consult a doctor" in ans.answer


def test_general_knowledge_fallback_never_answers_non_health(make_pipeline, settings):
    llm = _GeneralKnowledgeLLM(health=False)
    p = make_pipeline(llm)
    p.s = settings.model_copy(update={"general_knowledge_fallback": True})
    ans = p.answer("What is the capital of plinthland?")
    assert ans.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "unverified_general_knowledge" not in ans.safety.flags
    assert not any(c.startswith("You are AyuMitra, a careful health-education") for c in llm.calls)


def test_wikipedia_tier_only_for_health_questions(make_pipeline, settings):
    from ayumitra_ai.external import ExternalDoc

    class StubExternal:
        def __init__(self):
            self.wiki_calls = 0

        def search(self, question, medicines=()):
            return []  # official sources have nothing

        def wikipedia(self, question):
            self.wiki_calls += 1
            return [ExternalDoc(id="ext-wiki-1", title="Plinthectomy (Wikipedia)", url="https://en.wikipedia.org/wiki/Plinthectomy",
                                publisher="Wikipedia (community encyclopedia, CC BY-SA)",
                                text="Plinthectomy is a fictional operation used only in software tests.")]

    claim = "Plinthectomy is a fictional operation used only in software tests."

    class LLM(_GeneralKnowledgeLLM):
        def complete(self, messages, *, json_schema=None, max_tokens=None, temperature=None):
            if json_schema and "claims" in json_schema.get("properties", {}) and "Plinthectomy is a fictional" in messages[-1]["content"]:
                return json.dumps({"status": "answered", "claims": [{"section": "direct_answer", "text": claim,
                                                                    "evidence_ids": ["E1"], "quote": claim}]})
            return super().complete(messages, json_schema=json_schema, max_tokens=max_tokens, temperature=temperature)

    for health, expect in ((True, AnswerStatus.ANSWERED), (False, AnswerStatus.INSUFFICIENT_EVIDENCE)):
        p = make_pipeline(LLM(health=health))
        p.s = settings.model_copy(update={"external_sources_enabled": True, "wikipedia_contact": "https://example.org/app"})
        p.external = StubExternal()
        ans = p.answer("What is a plinthectomy?")
        assert ans.status == expect
        if health:
            assert ans.citations[0].url.startswith("https://en.wikipedia.org/") and "wikipedia" in ans.safety.flags
        else:
            assert p.external.wiki_calls == 0  # non-health questions never reach Wikipedia


def test_fragment_and_duplicate_claims_are_rejected(make_pipeline):
    """Regression: '... and more common than in placebo-treated patients, are listed in Table 1.' was shown
    four times as the metformin answer."""
    frag = "... zentrine reactions more common than placebo are listed in Table 1."
    good = "A zentrine level above 42 units may mean Kelvara syndrome."
    p = make_pipeline(FakeLLM(lambda prompt: [{"section": "direct_answer", "text": frag, "evidence_ids": ["E1"], "quote": ""},
                                              {"section": "explanation", "text": good, "evidence_ids": ["E1"], "quote": ""},
                                              {"section": "key_points", "text": good, "evidence_ids": ["E1"], "quote": ""}]))
    ans = p.answer("What does a high zentrine level mean?")
    assert "Table 1" not in ans.answer and ans.answer.count("Kelvara syndrome") == 1
    reasons = [c.reason for c in ans.rejected_claims]
    assert "not a complete sentence" in reasons and "repeats an earlier sentence" in reasons


def test_truncated_model_output_keeps_completed_claims():
    """Regression: a reply cut off by the token limit raised JSONDecodeError -> HTTP 500 -> 'AI unavailable'."""
    cut = ('{"status": "answered", "claims": [{"section": "direct_answer", "text": "Zentrine is a protein.", '
           '"evidence_ids": ["E1"], "quote": "Zentrine is a protein."}, {"section": "explanation", "text": "It is mea')
    status, claims = parse_generation(cut)
    assert status == "answered" and [c.text for c in claims] == ["Zentrine is a protein."]


def test_unparseable_output_falls_back_instead_of_crashing(make_pipeline):
    class Garbage(FakeLLM):
        def complete(self, messages, *, json_schema=None, max_tokens=None, temperature=None):
            return "not json at all"

    ans = make_pipeline(Garbage()).answer("What does a high zentrine level mean?")
    assert ans.status == AnswerStatus.INSUFFICIENT_EVIDENCE


def test_evidence_drops_ellipsis_and_table_fragments():
    from ayumitra_ai.evidence import _is_fragment

    assert _is_fragment("... and more common than in placebo-treated patients, are listed in Table 1.")
    assert _is_fragment("and upper respiratory tract infections.")
    assert not _is_fragment("Diarrhea and nausea were the most common side effects.")


def test_near_duplicate_claims_are_dropped():
    from ayumitra_ai.pipeline import drop_near_duplicates
    from ayumitra_ai.schemas import ValidatedClaim

    def mk(t):
        return ValidatedClaim(text=t, evidence_ids=["E1"], supported=True, support_score=1.0, method="nli")

    kept = drop_near_duplicates([
        mk("These zentrine effects occur in more than 5 percent of patients using Kelvarol."),
        mk("The zentrine effects occur in more than 5 percent of patients, so they are common with Kelvarol."),
        mk("Kelvarol is a fictional medicine used only in software tests."),
    ])
    assert [k.text[:12] for k in kept] == ["These zentri", "Kelvarol is "]
