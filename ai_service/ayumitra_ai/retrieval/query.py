"""
Query rewriting and multi-query generation.

Two strategies, both optional and both bounded:
1. Deterministic: expand standard medical abbreviations ("hba1c" -> "glycated hemoglobin A1C") and
   strip conversational filler so keyword search sees the medical terms. Fast, no model.
2. LLM-based: ask Qwen for up to N alternative phrasings of a patient question. Off by default on CPU.

Every variant is used *only for retrieval*; the original question is what gets answered.
"""

from __future__ import annotations

import json
import re

# Standard abbreviation expansions (terminology, not medical claims). Keep conservative.
ABBREVIATIONS: dict[str, str] = {
    "hba1c": "hemoglobin A1C glycated hemoglobin",
    "a1c": "hemoglobin A1C",
    "hb": "hemoglobin",
    "hgb": "hemoglobin",
    "ldl": "LDL low-density lipoprotein cholesterol",
    "hdl": "HDL high-density lipoprotein cholesterol",
    "tsh": "thyroid stimulating hormone",
    "cbc": "complete blood count",
    "wbc": "white blood cell count",
    "rbc": "red blood cell count",
    "bmp": "basic metabolic panel",
    "lft": "liver function tests",
    "lfts": "liver function tests",
    "egfr": "estimated glomerular filtration rate kidney",
    "bp": "blood pressure",
    "fbs": "fasting blood sugar glucose",
    "rbs": "random blood sugar glucose",
    "ppbs": "postprandial blood sugar glucose after meal",
    "t2dm": "type 2 diabetes",
    "dm": "diabetes",
    "htn": "hypertension high blood pressure",
    "ckd": "chronic kidney disease",
    "vit": "vitamin",
    "sgpt": "ALT alanine transaminase liver",
    "sgot": "AST aspartate aminotransferase liver",
    "alt": "alanine transaminase liver",
    "ast": "aspartate aminotransferase liver",
    # chemical / alternative names of common vitamins (synonyms only; retrieval still decides relevance)
    "tocopherol": "vitamin E",
    "tocopherols": "vitamin E",
    "cobalamin": "vitamin B12",
    "cyanocobalamin": "vitamin B12",
    "cholecalciferol": "vitamin D3",
    "ergocalciferol": "vitamin D2",
    "calciferol": "vitamin D",
    "retinol": "vitamin A",
    "ascorbic": "vitamin C",
    "thiamine": "vitamin B1",
    "riboflavin": "vitamin B2",
    "folate": "folic acid vitamin B9",
}

_FILLER = re.compile(
    r"\b(hi|hello|please|kindly|can you|could you|tell me|i want to know|i would like to know|"
    r"explain( to me)?|my doctor said|i was told|in simple words|in simple terms)\b",
    re.IGNORECASE,
)


def expand_abbreviations(query: str) -> str:
    def repl(m: re.Match) -> str:
        word = m.group(0)
        exp = ABBREVIATIONS.get(word.lower())
        return f"{word} ({exp})" if exp else word

    return re.sub(r"\b[A-Za-z][A-Za-z0-9]{1,15}\b", repl, query)


def strip_filler(query: str) -> str:
    q = _FILLER.sub(" ", query)
    return re.sub(r"\s+", " ", q).strip(" ,.?") or query


def deterministic_rewrites(question: str) -> list[str]:
    variants = [question]
    cleaned = strip_filler(question)
    expanded = expand_abbreviations(cleaned)
    for v in (cleaned, expanded):
        if v.lower() != question.lower() and v not in variants:
            variants.append(v)
    return variants


REWRITE_PROMPT = (
    "Rewrite the patient's question into {n} short search queries for a medical knowledge base. "
    "Use standard medical terms. Do not answer the question and do not add facts. "
    'Reply with JSON only: {{"queries": ["...", "..."]}}\n\nQuestion: {question}'
)


def llm_rewrites(question: str, llm, n: int = 2) -> list[str]:
    """Ask the LLM for alternative phrasings. Any failure simply yields no extra queries."""
    try:
        raw = llm.complete(
            [{"role": "user", "content": REWRITE_PROMPT.format(n=n, question=question)}],
            json_schema={
                "type": "object",
                "properties": {"queries": {"type": "array", "items": {"type": "string"}, "maxItems": n}},
                "required": ["queries"],
            },
            max_tokens=120,
        )
        queries = json.loads(raw).get("queries", [])
        return [q.strip() for q in queries if isinstance(q, str) and 3 <= len(q.strip()) <= 200][:n]
    except Exception:
        return []


def build_queries(question: str, *, llm=None, use_llm: bool = False, max_queries: int = 4) -> list[str]:
    queries = deterministic_rewrites(question)
    if use_llm and llm is not None:
        for q in llm_rewrites(question, llm):
            if q.lower() not in {x.lower() for x in queries}:
                queries.append(q)
    return queries[:max_queries]
