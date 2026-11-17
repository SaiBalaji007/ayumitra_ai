"""
Medical named-entity recognition with a pretrained biomedical token-classification model.

Model: d4data/biomedical-ner-all (DistilBERT trained on the MACCROBAT clinical case corpus,
107 entity types including Disease_disorder, Sign_symptom, Medication, Lab_value,
Diagnostic_procedure, Dosage). Used as-is; no fine-tuning.

Why not scispaCy: on Python 3.13 its required `nmslib` dependency doesn't build, and its models
pin older spaCy versions. The transformers model covers the same entity families here.

Output entities carry character offsets into the input text and the model's confidence, so
every entity can be traced back to the document.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

DEFAULT_MODEL = "d4data/biomedical-ner-all"

# Model labels -> AyuMitra entity categories
CATEGORY = {
    "disease_disorder": "disease", "sign_symptom": "symptom", "medication": "medication",
    "lab_value": "lab_value", "diagnostic_procedure": "test", "dosage": "dosage", "frequency": "frequency",
    "duration": "duration", "administration": "route", "biological_structure": "anatomy",
    "therapeutic_procedure": "procedure", "severity": "severity", "date": "date", "age": "age", "sex": "sex",
    "clinical_event": "event", "detailed_description": "description", "history": "history",
}


@dataclass
class Entity:
    text: str
    label: str        # model label, e.g. Disease_disorder
    category: str     # AyuMitra category, e.g. disease
    start: int
    end: int
    confidence: float

    def to_dict(self):
        return asdict(self)


class MedicalNER:
    def __init__(self, model_id: str = DEFAULT_MODEL, device: int = -1):
        from transformers import pipeline

        self.model_id = model_id
        self._nlp = pipeline("token-classification", model=model_id, aggregation_strategy="simple", device=device)

    def extract(self, text: str, *, min_confidence: float = 0.5) -> list[Entity]:
        if not text.strip():
            return []
        out = []
        # The model has a 512-token window; process paragraph-sized pieces and keep global offsets.
        offset = 0
        for piece in _windows(text, 1500):
            for e in self._nlp(piece):
                score = float(e["score"])
                if score < min_confidence:
                    continue
                label = str(e["entity_group"])
                start, end = offset + int(e["start"]), offset + int(e["end"])
                out.append(Entity(text=text[start:end], label=label, category=CATEGORY.get(label.lower(), "other"),
                                  start=start, end=end, confidence=round(score, 3)))
            offset += len(piece)
        return out


def _windows(text: str, size: int) -> list[str]:
    pieces, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start, end)
            cut = cut if cut > start + size // 2 else text.rfind(" ", start, end)
            end = cut + 1 if cut > start else end
        pieces.append(text[start:end])
        start = end
    return pieces


@lru_cache(maxsize=1)
def default_ner() -> MedicalNER:
    return MedicalNER()
