"""
Citation validation: every claim must be supported by the specific passages it cites.

A claim passes only if all of these hold:
  1. It cites at least one evidence id, and every cited id was actually retrieved (no invented sources).
  2. Every number in the claim appears in the cited passages (no invented values or doses).
  3. It is supported by a cited sentence: either an NLI entailment model (pretrained cross-encoder)
     judges it entailed, or, when the model offered a quote, that quote is found verbatim in the
     cited evidence and has strong lexical overlap with the claim.
Claims that fail are removed from the answer and reported in `rejected_claims`.
"""

from __future__ import annotations

import re

from .models import EntailmentModel
from .schemas import Claim, Evidence, ValidatedClaim
from .text import content_terms, extract_numbers, normalize_for_match


def _quote_in_evidence(quote: str, evs: list[Evidence]) -> Evidence | None:
    q = normalize_for_match(quote)
    if len(q) < 12:
        return None
    for ev in evs:
        if q in normalize_for_match(ev.text):
            return ev
    return None


def lexical_support(claim: str, passage: str) -> float:
    terms = content_terms(claim)
    return len(terms & content_terms(passage)) / len(terms) if terms else 0.0


_NEGATION = re.compile(r"\b(not|no|never|none|neither|nor|without|cannot)\b|n't\b", re.I)


def _negated(text: str) -> bool:
    return bool(_NEGATION.search(text))


def _spelling_fold(t: str) -> str:
    """British/American variants are the same word: anaemia/anemia, haemoglobin/hemoglobin, tumour/tumor."""
    return t.replace("ae", "e").replace("oe", "e").replace("our", "or").replace("ise", "ize")


def garbled_terms(claim: str, reference_text: str) -> list[str]:
    """Words in the claim that look like a corrupted copy of a word in the question or evidence,
    e.g. "tocoproil" for "tocopherol". NLI models often ignore such corruption, but showing a
    misspelled medical term to a patient is wrong, so these claims are rejected."""
    from difflib import SequenceMatcher

    ref = {_spelling_fold(r) for r in content_terms(reference_text) if len(r) >= 6}
    bad = []
    for t in content_terms(claim):
        f = _spelling_fold(t)
        if len(f) < 6 or f in ref:
            continue
        for r in ref:
            if f.startswith(r[:-2]) or r.startswith(f[:-2]):  # inflections: infection/infections, test/tested
                continue
            if abs(len(f) - len(r)) <= 3 and SequenceMatcher(None, f, r).ratio() >= 0.75:
                bad.append(t)
                break
    return bad


def _sentence_windows(evs: list[Evidence]) -> list[str]:
    """Each cited sentence and each adjacent pair (a list lead-in and its items may be two sentences)."""
    out = []
    for ev in evs:
        sents = [s.text for s in ev.sentences] or [ev.text]
        out.extend(sents)
        out.extend(f"{a} {b}" for a, b in zip(sents, sents[1:]))
    return out


class CitationValidator:
    def __init__(self, nli: EntailmentModel | None, *, entail_threshold: float = 0.5, lexical_threshold: float = 0.6,
                 close_restatement_threshold: float = 0.85):
        self.nli = nli
        self.close_restatement_threshold = close_restatement_threshold
        self.entail_threshold = entail_threshold
        self.lexical_threshold = lexical_threshold

    def validate(self, claim: Claim, evidence: dict[str, Evidence]) -> ValidatedClaim:
        def result(ok: bool, score: float, method: str, reason: str = "") -> ValidatedClaim:
            return ValidatedClaim(**claim.model_dump(), supported=ok, support_score=round(score, 3), method=method, reason=reason)

        ids = list(dict.fromkeys(claim.evidence_ids))
        if not ids:
            return result(False, 0, "none", "no citation")
        unknown = [i for i in ids if i not in evidence]
        if unknown:
            return result(False, 0, "none", f"cites evidence that was not retrieved: {', '.join(unknown)}")
        cited = [evidence[i] for i in ids]
        cited_text = " ".join(e.text for e in cited)

        missing_numbers = extract_numbers(claim.text) - extract_numbers(cited_text)
        if missing_numbers:
            return result(False, 0, "numbers", f"numbers not in cited evidence: {', '.join(sorted(missing_numbers))}")

        best, method = 0.0, "nli"
        if self.nli is not None:
            # Premises: each cited sentence, and each cited passage as a whole.
            premises = [s.text for e in cited for s in e.sentences] + [e.text for e in cited]
            for premise in premises:
                p = self.nli.entailment(premise, [claim.text])[0]
                best = max(best, p)
                if best >= self.entail_threshold:
                    return result(True, best, "nli")

        if claim.quote:
            ev = _quote_in_evidence(claim.quote, cited)
            if ev is not None:
                overlap = lexical_support(claim.text, claim.quote)
                if overlap >= self.lexical_threshold:
                    return result(True, max(best, overlap), "verbatim_quote")

        # Close restatement of one cited sentence (or adjacent pair). The small NLI model is brittle with
        # near-verbatim paraphrases ("white cell count" -> "white blood cell count" scores 0.005), so a
        # claim whose content words are >= 85 % contained in a single cited sentence, with the same
        # negation polarity, is accepted. Added facts ("...and teeth", "...leading to fatigue") stay
        # below the bar because each one adds unsupported words.
        if self.nli is not None:
            for window in _sentence_windows(cited):
                overlap = lexical_support(claim.text, window)
                if overlap >= self.close_restatement_threshold and _negated(claim.text) == _negated(window):
                    return result(True, max(best, overlap), "close_restatement")

        if self.nli is None:
            overlap = max(lexical_support(claim.text, e.text) for e in cited)
            method = "lexical"
            if overlap >= self.lexical_threshold:
                return result(True, overlap, method)
            best = overlap
        return result(False, best, method, "not supported by the cited passages")
