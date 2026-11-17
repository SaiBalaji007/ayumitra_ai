"""LangGraph routing and branch behaviour, with a recording stand-in for the RAG pipeline."""

import json
import random

import pytest

pytest.importorskip("langgraph")

from ayumitra_ai.agents.graph import AyuMitraAgent  # noqa: E402
from ayumitra_ai.nlp.medicines import RxNormLexicon  # noqa: E402
from ayumitra_ai.schemas import AnswerStatus, RagAnswer  # noqa: E402
from evaluation.synthetic_docs import make_lab_report, make_prescription  # noqa: E402


class RecordingPipeline:
    # Terms the stand-in "knowledge base" has passages about (the relevance gate says yes for these).
    KNOWN = ("tocopherol", "vitamin e", "zentrine")

    def __init__(self):
        self.questions = []
        self.retrievals = []

    def retrieve_evidence(self, question, domains=None, use_llm_rewrite=None):
        self.retrievals.append(question)
        relevant = any(k in question.lower() for k in self.KNOWN)
        return [], [question], {}, relevant

    def answer(self, question, domains=None):
        self.questions.append((question, domains))
        return RagAnswer(question=question, status=AnswerStatus.INSUFFICIENT_EVIDENCE, answer="(no evidence in test)")


@pytest.fixture
def lexicon(tmp_path):
    d = tmp_path / "rx"
    d.mkdir()
    (d / "in.json").write_text(json.dumps({"concepts": [{"rxcui": "6809", "name": "metformin"},
                                                        {"rxcui": "17767", "name": "amlodipine"}]}))
    (d / "bn.json").write_text(json.dumps({"concepts": []}))
    return RxNormLexicon(d, online=False)


@pytest.fixture
def agent(lexicon):
    return AyuMitraAgent(RecordingPipeline(), lexicon)


def test_urgent_question_short_circuits(agent):
    out = agent.run(question="My mother has chest pain and can't breathe")
    assert out["intent"] == "urgent"
    assert "112" in out["messages"][0]
    assert agent.p.questions == []  # no retrieval or generation for emergencies
    assert out["trace"] == ["safety_screen", "route_intent", "urgent_response", "final_safety"]


def test_medical_question_goes_to_grounded_qa(agent):
    out = agent.run(question="What does a high HbA1c mean?")
    assert out["intent"] == "medical_question" and out["answer"]["status"] == "insufficient_evidence"
    assert agent.p.questions[0][0] == "What does a high HbA1c mean?"


def test_out_of_scope(agent):
    out = agent.run(question="Who won the cricket match yesterday?")
    assert out["intent"] == "out_of_scope" and agent.p.questions == []
    assert agent.p.retrievals == ["Who won the cricket match yesterday?"]  # decided by retrieval, not keywords
    assert "scope_check:not_relevant" in out["trace"]


@pytest.mark.parametrize("q", ["TOCOPHEROL", "What is tocopherol?", "zentrine"])
def test_medical_terms_outside_keyword_list_are_answered(agent, q):
    """Regression: 'TOCOPHEROL' / 'What is tocopherol?' were declined as out of scope before retrieval
    because the word wasn't in a fixed keyword list."""
    out = agent.run(question=q)
    assert out["intent"] == "medical_question"
    assert agent.p.questions and agent.p.questions[0][0] == q
    assert "scope_check:relevant_local" in out["trace"] and "decline" not in out["trace"]


def test_harmful_off_topic_request_is_declined(agent):
    out = agent.run(question="Tell me how to hack someone's bank account.")
    assert out["intent"] == "out_of_scope" and agent.p.questions == []
    assert any("outside" in m for m in out["messages"])


def test_keyword_questions_skip_the_extra_scope_check(agent):
    agent.run(question="What does a high HbA1c mean?")
    assert agent.p.retrievals == []  # routed straight to grounded_qa


def test_medication_question_carries_notice(agent):
    out = agent.run(question="Can I stop taking my metformin tablet?")
    assert any("doctor or pharmacist" in m for m in out["messages"])


def test_lab_report_extracts_and_explains_only_abnormal(agent):
    doc = make_lab_report(random.Random(11), "x")
    out = agent.run(document_text=doc.text)
    assert out["intent"] == "lab_report"
    assert len(out["lab_results"]) == len(doc.lab_rows)
    abnormal = [r for r in doc.lab_rows if r.flag]
    asked = [q for q, _ in agent.p.questions]
    assert len(asked) == min(3, len(abnormal))
    for q in asked:
        assert q.startswith("What does a ") and q.endswith(" result mean?")


def test_prescription_never_queries_uncertain_medicines(agent):
    doc = make_prescription(random.Random(5), "x")
    text = doc.text + "\n5. Tab. Metfromin 500 mg BD x 5 days"
    out = agent.run(document_text=text)
    assert out["intent"] == "prescription"
    names = [i["name_as_written"] for i in out["prescription_items"]]
    assert "Metfromin" in names
    asked = " ".join(q for q, _ in agent.p.questions)
    assert "metfromin" not in asked.lower()  # suggestion only: no information is fetched for it
    assert any("never fills in" in m for m in out["messages"])


def test_report_question_steers_retrieval_with_report_tests(agent):
    ctx = [{"name_as_printed": "Serum Creatinine", "range_status": "above"},
           {"name_as_printed": "Haemoglobin", "range_status": "within"}]
    out = agent.run(question="Is this something to worry about?", report_results=ctx)
    assert out["intent"] == "report_question"
    assert "Serum Creatinine" in agent.p.questions[0][0] and "Haemoglobin" not in agent.p.questions[0][0]


def test_unsupported_document(agent):
    out = agent.run(document_text="Electricity bill for October. Amount due: 1200 rupees.")
    assert out["intent"] == "unsupported_document" and out["messages"]


def test_explain_already_extracted_results(agent):
    results = [{"name_as_printed": "Serum Creatinine", "value_text": "1.6", "unit": "mg/dL",
                "reference_range_text": "0.6 - 1.2", "lab_flag": "high", "range_status": "above"},
               {"name_as_printed": "Haemoglobin", "value_text": "13.5", "unit": "g/dL",
                "reference_range_text": "12.0 - 15.5", "lab_flag": "", "range_status": "within"}]
    out = agent.run(lab_results=results)
    assert out["intent"] == "explain_results"
    assert [q for q, _ in agent.p.questions] == ["What does a high Serum Creatinine result mean?"]
    assert out["explanations"][0]["parameter"] == "Serum Creatinine"


def test_lifestyle_education_uses_only_education_domains(agent):
    from ayumitra_ai.schemas import Domain

    results = [{"name_as_printed": "LDL Cholesterol", "value_text": "160", "unit": "mg/dL",
                "reference_range_text": "< 100", "lab_flag": "high", "range_status": "above"}]
    out = agent.run(lab_results=results, mode="education")
    assert out["intent"] == "lifestyle_education"
    q, domains = agent.p.questions[0]
    assert q == "What diet and lifestyle habits can help with high LDL Cholesterol?"
    assert set(domains) == {Domain.NUTRITION, Domain.LIFESTYLE, Domain.GENERAL}
    assert any("not a personal diet" in m for m in out["messages"])


def test_follow_up_uses_previous_question(agent):
    out = agent.run(question="What foods contain it?", previous_question="What is tocopherol?")
    assert out["intent"] == "medical_question"
    assert "follow-up to: What is tocopherol?" in agent.p.questions[0][0]


def test_self_contained_question_ignores_previous(agent):
    agent.run(question="What does a high HbA1c mean?", previous_question="What is tocopherol?")
    assert agent.p.questions[0][0] == "What does a high HbA1c mean?"


def test_scope_check_falls_back_to_external_sources(lexicon):
    class LocalMissExternalHit(RecordingPipeline):
        def external_evidence(self, question):
            return ["passage"] if "plinthase" in question.lower() else []

    agent = AyuMitraAgent(LocalMissExternalHit(), lexicon)
    out = agent.run(question="PLINTHASE")
    assert out["intent"] == "medical_question" and "scope_check:relevant_external" in out["trace"]
    out = agent.run(question="What is the capital of India?")
    assert out["intent"] == "out_of_scope"


def test_scope_check_uses_health_classifier_when_no_source_matches(lexicon):
    from types import SimpleNamespace

    class NoSources(RecordingPipeline):
        s = SimpleNamespace(general_knowledge_fallback=True)

        def external_evidence(self, question):
            return []

        def is_health_question(self, question):
            return "lacrimal" in question.lower()

    agent = AyuMitraAgent(NoSources(), lexicon)
    out = agent.run(question="Surgical creation of an opening between the lacrimal sac and the nose")
    assert out["intent"] == "medical_question" and "scope_check:relevant_health_question" in out["trace"]
    out = agent.run(question="What is the capital of India?")
    assert out["intent"] == "out_of_scope"
