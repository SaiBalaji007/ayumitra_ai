"""Grounded answer generation with Qwen: evidence in, schema-constrained JSON claims out."""

from __future__ import annotations

import json
import re

from .evidence import format_evidence_for_prompt
from .schemas import CLAIM_SECTIONS, Claim, Evidence

SYSTEM_PROMPT = """You are AyuMitra, a careful health-information assistant for patients in India.
Answer ONLY from the numbered evidence passages provided. Rules:
- Every claim must be one short, plain-language sentence supported by the evidence ids it cites.
- Write 3 to 7 claims. Each claim restates ONE evidence sentence (or one list from it); never merge
  facts from different sentences into one claim and never add examples the sentence does not give.
- Copy the exact supporting sentence from the evidence into "quote".
- Never add facts, numbers, medicine names, doses or sources that are not in the evidence.
- Do not diagnose the user and do not tell them which medicine or dose to take.
- If the evidence does not answer the question, set "status" to "insufficient_evidence" and give no claims.
- Use simple words a patient can understand. Explain medical terms in plain words.
- Give each claim a "section":
  "direct_answer" - one claim that answers the question directly (always first);
  "explanation"   - 1 to 3 claims explaining the topic in more detail;
  "key_points"    - 1 to 3 claims on causes, symptoms, risks, foods, side effects or precautions, if the evidence has them;
  "see_doctor"    - when to see a doctor, ONLY if the evidence says so.
- Write at most 8 claims."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
        "claims": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 300},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                    "quote": {"type": "string", "maxLength": 300},
                    "section": {"type": "string", "enum": ["direct_answer", "explanation", "key_points", "see_doctor"]},
                },
                "required": ["section", "text", "evidence_ids", "quote"],
            },
        },
    },
    "required": ["status", "claims"],
}


def build_messages(question: str, evidence: list[Evidence]) -> list[dict]:
    user = (
        f"Evidence passages:\n\n{format_evidence_for_prompt(evidence)}\n\n"
        f"Question: {question}\n\n"
        'Reply with JSON only, matching: {"status": "answered" | "insufficient_evidence", '
        '"claims": [{"section": "direct_answer", "text": "...", "evidence_ids": ["E1"], "quote": "exact sentence from the evidence"}]}'
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _salvage_claims(raw: str) -> dict:
    """A reply cut off by the token limit ('Unterminated string ...'): keep every claim object that was
    completed before the cut. Incomplete claims are dropped, never repaired or guessed."""
    start = raw.find("[", raw.find('"claims"'))
    if start < 0:
        raise ValueError("no claims array in model output")
    dec, claims, i = json.JSONDecoder(), [], start + 1
    while True:
        j = raw.find("{", i)
        if j < 0:
            break
        try:
            obj, end = dec.raw_decode(raw, j)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            claims.append(obj)
        i = end
    return {"status": "answered" if claims else "insufficient_evidence", "claims": claims}


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)  # tolerate a fenced or prefixed reply
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return _salvage_claims(raw)


def parse_generation(raw: str) -> tuple[str, list[Claim]]:
    data = _extract_json(raw)
    status = data.get("status", "answered")
    claims = []
    for c in data.get("claims") or []:
        if not isinstance(c, dict) or not str(c.get("text", "")).strip():
            continue
        ids = [str(i).strip().strip("[]").upper() for i in (c.get("evidence_ids") or []) if str(i).strip()]
        section = c.get("section") if c.get("section") in CLAIM_SECTIONS else "explanation"
        claims.append(Claim(text=str(c["text"]).strip(), evidence_ids=ids, quote=(c.get("quote") or None), section=section))
    return status, claims


def generate_claims(llm, question: str, evidence: list[Evidence]) -> tuple[str, list[Claim], str]:
    raw = llm.complete(build_messages(question, evidence), json_schema=ANSWER_SCHEMA)
    status, claims = parse_generation(raw)
    return status, claims, raw
