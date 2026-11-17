"""
LangGraph workflow: intent routing and conditional branches over the grounded RAG pipeline.

  START -> safety_screen -> route_intent -+- urgent           -> urgent_response
                                          +- lab_report       -> extract_labs -> explain_abnormal
                                          +- explain_results  -> explain_abnormal (results from Django)
                                          +- lifestyle_education -> diet/lifestyle education for abnormal results
                                          +- prescription     -> extract_prescription -> medicine_info
                                          +- report_question  -> grounded_qa (question + report context)
                                          +- medical_question -> grounded_qa
                                          +- out_of_scope     -> decline
                                     all branches -> final_safety -> END

Every explanation comes from RagPipeline.answer, so it's retrieved, generated as JSON claims and
citation-validated. Branches only decide *what* to ask; they never write medical content.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from ..documents.classify import classify
from ..nlp.lab_extraction import LabResult, extract_lab_results
from ..nlp.medicines import RxNormLexicon
from ..nlp.prescriptions import extract_prescription
from ..safety import screen_question
from ..schemas import AnswerStatus, Domain


class AgentState(TypedDict, total=False):
    # inputs
    question: str
    document_text: str
    document_lines: list[str]
    line_confidences: list[float | None]
    report_results: list[dict]          # previously extracted results (report-specific chat)
    previous_question: str              # the user's previous question in this conversation
    mode: str                           # "explain" (default) or "education" for lab_results
    # derived
    intent: str
    document_type: str
    safety: dict
    lab_results: list[dict]
    prescription_items: list[dict]
    explanations: list[dict]
    answer: dict | None
    messages: list[str]
    trace: list[str]


MEDICAL_HINTS = re.compile(
    r"\b(test|result|level|report|blood|sugar|glucose|cholesterol|hemoglobin|haemoglobin|thyroid|tsh|vitamin|kidney|"
    r"liver|creatinine|urine|diabetes|pressure|bp|anemia|anaemia|platelet|wbc|cbc|hba1c|a1c|ldl|hdl|triglyceride|"
    r"uric|ferritin|symptom|disease|medicine|medication|tablet|dose|doctor|pain|fever|health|diet|exercise|"
    r"normal|high|low|range|mean)\b",
    re.I,
)


def _explain_question(r: dict) -> str:
    direction = {"above": "high", "below": "low"}.get(r["range_status"]) or r["lab_flag"].replace("critical_", "")
    name = r["name_as_printed"]
    return f"What does a {direction} {name} result mean?"


_FOLLOW_UP = re.compile(
    r"^\s*(and|also|what about|how about|so|then)\b|\b(it|its|it's|this|that|these|those|they|them|their)\b", re.I)


def contextual_question(question: str, previous: str | None) -> str:
    """A short follow-up ("what foods contain it?") is searched together with the previous question;
    a self-contained question is left alone."""
    if not previous or not question:
        return question
    if len(question.split()) <= 10 and _FOLLOW_UP.search(question):
        return f"{question} (follow-up to: {previous.strip()})"
    return question


class AyuMitraAgent:
    def __init__(self, pipeline, lexicon: RxNormLexicon | None = None, *, max_explanations: int = 3):
        self.p = pipeline
        self.lexicon = lexicon
        self.max_explanations = max_explanations
        self.graph = self._build()

    # ---------------- nodes ----------------
    def safety_screen(self, s: AgentState) -> AgentState:
        text = s.get("question") or ""
        rep = screen_question(text)
        return {"safety": rep.model_dump(), "trace": [*s.get("trace", []), "safety_screen"]}

    def route_intent(self, s: AgentState) -> AgentState:
        trace = [*s.get("trace", []), "route_intent"]
        if s["safety"].get("urgent"):
            return {"intent": "urgent", "trace": trace}
        if s.get("document_text") or s.get("document_lines"):
            text = s.get("document_text") or "\n".join(s["document_lines"])
            c = classify(text)
            if c.document_type in ("lab_report", "prescription"):
                return {"intent": c.document_type, "document_type": c.document_type, "trace": trace}
            return {"intent": "unsupported_document", "document_type": c.document_type, "trace": trace}
        q = s.get("question") or ""
        if s.get("lab_results") and not q:
            # results already extracted by Django: explain them, or give diet/lifestyle education
            intent = "lifestyle_education" if s.get("mode") == "education" else "explain_results"
            return {"intent": intent, "trace": trace}
        if s.get("report_results"):
            return {"intent": "report_question", "trace": trace}
        if MEDICAL_HINTS.search(q) or MEDICAL_HINTS.search(contextual_question(q, s.get("previous_question"))):
            return {"intent": "medical_question", "trace": trace}
        # No keyword match ("TOCOPHEROL", "What is ferritin?", a medicine name...). A keyword list can
        # never cover medicine, so don't decline here: let retrieval decide in scope_check.
        return {"intent": "check_scope", "trace": trace}

    def urgent_response(self, s: AgentState) -> AgentState:
        return {"messages": [s["safety"]["urgent_message"]], "trace": [*s["trace"], "urgent_response"]}

    def extract_labs(self, s: AgentState) -> AgentState:
        lines = s.get("document_lines") or (s.get("document_text") or "").splitlines()
        results = extract_lab_results(lines, line_confidences=s.get("line_confidences"))
        return {"lab_results": [r.to_dict() for r in results], "trace": [*s["trace"], "extract_labs"]}

    def explain_abnormal(self, s: AgentState) -> AgentState:
        abnormal = [r for r in s.get("lab_results", []) if r["range_status"] in ("above", "below") or r["lab_flag"]]
        explanations = []
        for r in abnormal[: self.max_explanations]:
            ans = self.p.answer(_explain_question(r), domains=[Domain.LAB_TESTS, Domain.GENERAL])
            explanations.append({"parameter": r["name_as_printed"], "value": r["value_text"], "unit": r["unit"],
                                 "reference_range": r["reference_range_text"], "lab_flag": r["lab_flag"],
                                 "range_status": r["range_status"], "answer": ans.model_dump(mode="json")})
        msgs = []
        if len(abnormal) > self.max_explanations:
            msgs.append(f"{len(abnormal) - self.max_explanations} more results are outside the lab's range; "
                        "ask about any of them for an explanation.")
        if not abnormal and s.get("lab_results"):
            msgs.append("All extracted results are within the reference ranges printed by your laboratory.")
        return {"explanations": explanations, "messages": msgs, "trace": [*s["trace"], "explain_abnormal"]}

    def lifestyle_education(self, s: AgentState) -> AgentState:
        """Personalised *education*: diet/lifestyle information relevant to results outside the lab range,
        only from the nutrition/lifestyle/general knowledge domains. Abstains when sources don't cover it."""
        abnormal = [r for r in s.get("lab_results", []) if r["range_status"] in ("above", "below") or r["lab_flag"]]
        explanations = []
        for r in abnormal[: self.max_explanations]:
            direction = {"above": "high", "below": "low"}.get(r["range_status"]) or r["lab_flag"].replace("critical_", "")
            q = f"What diet and lifestyle habits can help with {direction} {r['name_as_printed']}?"
            ans = self.p.answer(q, domains=[Domain.NUTRITION, Domain.LIFESTYLE, Domain.GENERAL])
            explanations.append({"parameter": r["name_as_printed"], "value": r["value_text"], "unit": r.get("unit", ""),
                                 "reference_range": r.get("reference_range_text", ""), "lab_flag": r["lab_flag"],
                                 "range_status": r["range_status"], "answer": ans.model_dump(mode="json")})
        msgs = ["This is general education from trusted sources, not a personal diet or exercise plan. "
                "Talk to your doctor or a registered dietitian before making big changes."]
        if not abnormal:
            msgs.insert(0, "All results are within your laboratory's printed ranges.")
        return {"explanations": explanations, "messages": msgs, "trace": [*s["trace"], "lifestyle_education"]}

    def extract_rx(self, s: AgentState) -> AgentState:
        lines = s.get("document_lines") or (s.get("document_text") or "").splitlines()
        items = extract_prescription(lines, self.lexicon, s.get("line_confidences"))
        return {"prescription_items": [i.to_dict() for i in items], "trace": [*s["trace"], "extract_prescription"]}

    def medicine_info(self, s: AgentState) -> AgentState:
        explanations = []
        for item in s.get("prescription_items", []):
            med = item.get("medicine") or {}
            # Only medicines recognised exactly in RxNorm get information. Uncertain names wait for the user.
            if not med.get("status", "").startswith("exact") or not med.get("generic_name"):
                continue
            ans = self.p.answer(f"What is {med['generic_name']} used for and what are its common side effects?",
                                domains=[Domain.MEDICINES])
            explanations.append({"medicine": item["name_as_written"], "generic_name": med["generic_name"],
                                 "answer": ans.model_dump(mode="json")})
        msgs = ["Please check every extracted field against your prescription. AyuMitra never fills in a missing "
                "dose, frequency or duration."]
        if any(i["fields_needing_review"] for i in s.get("prescription_items", [])):
            msgs.append("Some fields could not be read confidently and are marked for your review.")
        return {"explanations": explanations, "messages": msgs, "trace": [*s["trace"], "medicine_info"]}

    def grounded_qa(self, s: AgentState) -> AgentState:
        q = contextual_question(s["question"], s.get("previous_question"))
        context = s.get("report_results") or []
        if context:
            # Retrieval-only context: the user's own values stay out of the knowledge base and out of
            # the evidence; we only steer the search towards the tests on their report.
            names = ", ".join(sorted({r["name_as_printed"] for r in context if r["range_status"] in ("above", "below")})[:4])
            if names and not any(n.lower() in q.lower() for n in names.split(", ")):
                q = f"{q} (about: {names})"
        ans = self.p.answer(q)
        return {"answer": ans.model_dump(mode="json"), "trace": [*s["trace"], "grounded_qa"]}

    def scope_check(self, s: AgentState) -> AgentState:
        """In scope if the trusted knowledge base has a relevant passage (cross-encoder relevance gate on
        real ChromaDB + BM25 retrieval). Off-topic requests ("hack a bank account") find nothing relevant
        and are declined; medical terms the keyword list doesn't know are answered normally."""
        q = contextual_question(s.get("question") or "", s.get("previous_question"))
        _, _, _, relevant = self.p.retrieve_evidence(q)
        where = "local"
        if not relevant and hasattr(self.p, "external_evidence"):
            # Not in the local knowledge base: a trusted external source (MedlinePlus, MeSH, FDA labels) may cover it.
            relevant, where = bool(self.p.external_evidence(q)), "external"
        if not relevant and getattr(getattr(self.p, "s", None), "general_knowledge_fallback", False) \
                and hasattr(self.p, "is_health_question"):
            # No source at all: still answer (labelled unverified) if the model confirms it's a health question.
            relevant, where = self.p.is_health_question(q), "health_question"
        intent = "medical_question" if relevant else "out_of_scope"
        tag = f"relevant_{where}" if relevant else "not_relevant"
        return {"intent": intent, "trace": [*s["trace"], f"scope_check:{tag}"]}

    def decline(self, s: AgentState) -> AgentState:
        msg = ("AyuMitra answers health questions using trusted medical sources. This question looks outside "
               "that scope." if s["intent"] == "out_of_scope" else
               "This document doesn't look like a lab report or prescription, so it wasn't analysed.")
        return {"messages": [msg], "trace": [*s["trace"], "decline"]}

    def final_safety(self, s: AgentState) -> AgentState:
        msgs = list(s.get("messages", []))
        safety = s.get("safety", {})
        for notice in safety.get("notices", []):
            if notice not in msgs:
                msgs.append(notice)
        if safety.get("urgent") and safety.get("urgent_message") not in msgs:
            msgs.insert(0, safety["urgent_message"])
        return {"messages": msgs, "trace": [*s["trace"], "final_safety"]}

    # ---------------- graph ----------------
    def _build(self):
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(AgentState)
        for name in ("safety_screen", "route_intent", "urgent_response", "extract_labs", "explain_abnormal", "lifestyle_education",
                     "extract_rx", "medicine_info", "scope_check", "grounded_qa", "decline", "final_safety"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "safety_screen")
        g.add_edge("safety_screen", "route_intent")
        g.add_conditional_edges("route_intent", lambda s: s["intent"], {
            "urgent": "urgent_response", "lab_report": "extract_labs", "prescription": "extract_rx",
            "explain_results": "explain_abnormal", "lifestyle_education": "lifestyle_education",
            "report_question": "grounded_qa", "medical_question": "grounded_qa",
            "out_of_scope": "decline", "unsupported_document": "decline", "check_scope": "scope_check",
        })
        g.add_conditional_edges("scope_check", lambda s: s["intent"], {
            "medical_question": "grounded_qa", "out_of_scope": "decline",
        })
        g.add_edge("extract_labs", "explain_abnormal")
        g.add_edge("extract_rx", "medicine_info")
        for n in ("urgent_response", "explain_abnormal", "lifestyle_education", "medicine_info", "grounded_qa", "decline"):
            g.add_edge(n, "final_safety")
        g.add_edge("final_safety", END)
        return g.compile()

    def run(self, **inputs: Any) -> AgentState:
        return self.graph.invoke({"trace": [], "messages": [], **inputs})


def answer_status(state: AgentState) -> str:
    ans = state.get("answer")
    return ans["status"] if ans else AnswerStatus.ANSWERED.value
