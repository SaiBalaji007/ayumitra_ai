"""
Medical safety validation: transparent, rule-based, and tested.

Input screening runs before retrieval: urgent symptoms, self-harm, and requests for personal
medication decisions. Output screening runs on every generated claim: diagnostic certainty
aimed at the user, dose instructions, and numbers that don't appear in the evidence.
Rules err on the side of caution; they never add medical content of their own.
"""

from __future__ import annotations

import re

from .schemas import SafetyReport

INDIA_EMERGENCY = "112"
TELE_MANAS = "14416"

_URGENT = [
    (r"\bchest (pain|tightness|pressure)\b", "chest pain"),
    (r"\b(can'?t|cannot|unable to|struggling to|difficulty) breath(e|ing)\b|\bshort(ness)? of breath\b", "breathing difficulty"),
    (r"\b(face|smile) (droop|drooping)|\bslurred speech\b|\bsudden(ly)? (weakness|numbness)\b|"
     r"\b(having|had|is having) a stroke\b", "stroke signs"),
    (r"\b(unconscious|passed out|fainted|not waking up|unresponsive|having a seizure|having fits)\b",
     "loss of consciousness or seizure"),
    (r"\b(heavy|severe|uncontrolled|won'?t stop) bleeding\b|\bvomiting blood\b|\bblood in (vomit|stool)\b", "severe bleeding"),
    (r"\b(overdose|overdosed|took too many|swallowed (poison|bleach))\b", "possible overdose or poisoning"),
    (r"\b(anaphyla\w*|throat (is )?(closing|swelling)|swollen (tongue|lips))\b", "severe allergic reaction"),
    (r"\bblood sugar (is )?(above|over) (400|500|600)\b|\bsugar (is )?(very )?(low|below 50)\b.*\b(confus|sweat|shak)", "dangerous blood sugar"),
]
_SELF_HARM = re.compile(r"\b(kill myself|suicid\w*|end my life|want to die|self[- ]harm|hurt myself)\b", re.I)

_MEDICATION_DECISION = re.compile(
    r"\b(how (much|many)\b.*\b(take|dose|tablets?|mg)|what dose|dosage of|double (the )?dose|"
    r"(can|should) i (stop|start|skip|increase|decrease|reduce|change)\b.*\b(medicine|medication|tablet|dose|insulin|drug)|"
    r"prescribe|which (medicine|tablet|drug) should i)\b",
    re.I,
)

# Output rules
_DIAGNOSTIC_CERTAINTY = re.compile(
    r"\byou (definitely |certainly |probably )?(have|are suffering from|are diagnosed with|have got)\b|"
    r"\byour (diagnosis|condition) is\b|\bthis (confirms|means you have)\b",
    re.I,
)
_DOSE_INSTRUCTION = re.compile(
    r"\b(take|use|inject|give)\b[^.]{0,40}\b\d+(\.\d+)?\s*(mg|mcg|µg|g|ml|units?|iu|tablets?|capsules?|puffs?)\b|"
    r"\b\d+(\.\d+)?\s*(mg|mcg|ml|units?|tablets?)\b[^.]{0,30}\b(daily|twice|once|every|per day|a day)\b",
    re.I,
)


def screen_question(question: str) -> SafetyReport:
    report = SafetyReport()
    q = question.lower()
    if _SELF_HARM.search(q):
        report.flags.append("self_harm")
        report.urgent = True
        report.urgent_message = (
            f"If you are thinking about harming yourself, please reach out now. In India, call Tele-MANAS at "
            f"{TELE_MANAS} (free, 24x7) or emergency services at {INDIA_EMERGENCY}. You are not alone."
        )
    for pattern, label in _URGENT:
        if re.search(pattern, q, re.I):
            report.flags.append(f"urgent:{label}")
            report.urgent = True
    if report.urgent and not report.urgent_message:
        report.urgent_message = (
            f"Some of what you describe can be a medical emergency. If it is happening now, call {INDIA_EMERGENCY} "
            "or go to the nearest emergency department. Don't wait for an online answer."
        )
    if _MEDICATION_DECISION.search(q):
        report.flags.append("medication_decision")
        report.notices.append(
            "AyuMitra can't decide doses or changes to your medicines. Please follow your prescription "
            "and ask your doctor or pharmacist before changing anything."
        )
    return report


# Telling the reader to stop, start or change a medicine is a clinical decision, whatever the source says
# (FDA labels contain prescriber instructions such as "advise patients to discontinue ...").
_MEDICATION_INSTRUCTION = re.compile(
    r"\b(you should|you must|you need to|stop|discontinue|start|begin|increase|decrease|reduce|double|skip|switch)\b"
    r"[^.]{0,40}\b(taking|medicine|medication|drug|dose|dosage|tablets?|pills?|insulin|treatment)\b",
    re.I,
)

_CONDITIONAL_BEFORE = re.compile(r"\b(if|when|whenever|whether|unless|once|in case|until)\s+(?:\w+\s+){0,2}$", re.I)


def _states_diagnosis(claim: str) -> bool:
    """'You have diabetes' is a diagnosis; 'If you have anemia, ...' or 'You may need the test if you
    have signs of infection' describe a situation and are fine."""
    for m in _DIAGNOSTIC_CERTAINTY.finditer(claim):
        if not _CONDITIONAL_BEFORE.search(claim[: m.start()]):
            return True
    return False


def screen_claim(claim: str, evidence_text: str, *, medication_question: bool) -> str | None:
    """Return a reason to reject this generated claim, or None if it passes."""
    if _states_diagnosis(claim):
        return "states a diagnosis about the user"
    if _MEDICATION_INSTRUCTION.search(claim) and not re.search(r"\b(talk|ask|check|speak|consult)\b", claim, re.I):
        return "tells the user to start, stop or change a medicine"
    if _DOSE_INSTRUCTION.search(claim):
        if medication_question:
            return "gives a dose instruction in reply to a personal medication question"
        if not _DOSE_INSTRUCTION.search(evidence_text):
            return "gives a dose instruction not present in the evidence"
    return None
