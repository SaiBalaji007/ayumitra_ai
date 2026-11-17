"""
Document classification: lab report, prescription, discharge summary, imaging report, other.

Transparent weighted cues (vocabulary plus layout signals such as table rows with units and
reference ranges, or "Rx"/"Tab."/"BD" medication lines). It returns scores and the cues found, so
the UI can show *why* and the user can correct it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CUES: dict[str, list[tuple[str, float]]] = {
    "lab_report": [
        (r"\breference (range|interval|value)s?\b|\bbiological ref", 3.0),
        (r"\b(mg/dl|g/dl|mmol/l|iu/l|u/l|cells/cumm|/cumm|10\^3/µl|10\^3/ul|fl|pg|%)\b", 1.0),
        (r"\b(haemoglobin|hemoglobin|hba1c|glucose|creatinine|cholesterol|triglycerides?|platelet|wbc|rbc|"
         r"sgpt|sgot|alt|ast|bilirubin|tsh|urea|uric acid|ferritin|vitamin d)\b", 1.0),
        (r"\b(specimen|sample (type|collected)|collected on|reported on|pathologist|laboratory|lab no)\b", 1.5),
        (r"\b(test name|investigation|result|units?)\b", 1.0),
    ],
    "prescription": [
        (r"(^|\s)(rx|℞)\b", 3.0),
        (r"\b(tab|tabs|cap|caps|syp|syr|inj|oint)\.?\s+[a-z]", 2.0),
        (r"\b(od|bd|bid|tds|tid|qid|hs|sos|stat|1-0-1|1-1-1|0-0-1|1-0-0)\b", 1.5),
        (r"\b(before|after) (food|meals?)\b|\bx\s?\d+\s?(days?|weeks?)\b|\bfor \d+ (days?|weeks?)\b", 1.5),
        (r"\b(dr\.|mbbs|md|reg\.? no|registration no|signature)\b", 1.0),
    ],
    "discharge_summary": [
        (r"\bdischarge (summary|date|advice|medications?)\b", 4.0),
        (r"\b(date of admission|admitted on|course in (the )?hospital|hospital course|final diagnosis)\b", 2.5),
    ],
    "imaging_report": [
        (r"\b(x-?ray|ultrasound|usg|ct scan|mri|sonography|radiolog\w*|impression)\b", 1.5),
        (r"\b(no (focal|acute) (lesion|abnormality)|echotexture|opacity|radiologist)\b", 2.5),
    ],
}

MIN_SCORE = 3.0


@dataclass
class Classification:
    document_type: str
    confidence: float
    scores: dict[str, float]
    cues: dict[str, list[str]] = field(default_factory=dict)


def classify(text: str) -> Classification:
    t = text.lower()
    scores: dict[str, float] = {}
    cues: dict[str, list[str]] = {}
    for label, patterns in CUES.items():
        score, found = 0.0, []
        for pattern, weight in patterns:
            hits = re.findall(pattern, t, re.M)
            if hits:
                # Diminishing returns: 5 matches of a cue are worth ~2.6x one match, not 5x.
                score += weight * min(3.0, 1 + 0.4 * (len(hits) - 1))
                found.append(re.search(pattern, t, re.M).group(0).strip())
        scores[label] = round(score, 2)
        if found:
            cues[label] = found
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    if scores[best] < MIN_SCORE:
        return Classification("other", 0.0, scores, cues)
    return Classification(best, round(scores[best] / total, 3) if total else 0.0, scores, cues)
