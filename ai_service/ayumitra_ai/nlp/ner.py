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

import os
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

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
        return _merge_fragments(out, text)


def _merge_fragments(ents: list[Entity], text: str) -> list[Entity]:
    """The tokenizer can split one word into several entities ("Am" + "lo" + "dipine"). Join touching entities of
    the same category back into the word as written."""
    merged: list[Entity] = []
    for e in ents:
        prev = merged[-1] if merged else None
        if prev and prev.category == e.category and e.start - prev.end <= 0:
            merged[-1] = Entity(text=text[prev.start:e.end], label=prev.label, category=prev.category, start=prev.start,
                                end=e.end, confidence=round(min(prev.confidence, e.confidence), 3))
        else:
            merged.append(e)
    return merged


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


LOCAL_MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ner" / "biomedical-ner-all"


def available() -> bool:
    return os.environ.get("AYUMITRA_NER_ENABLED", "true").lower() != "false" and (LOCAL_MODEL_DIR / "model.safetensors").exists()


@lru_cache(maxsize=1)
def default_ner() -> MedicalNER:
    """Loaded from the local copy (offline); falls back to the Hugging Face model id."""
    return MedicalNER(str(LOCAL_MODEL_DIR) if LOCAL_MODEL_DIR.exists() else DEFAULT_MODEL)


def possibly_missed_medicines(text: str, listed_names: list[str], ner: MedicalNER | None = None,
                              min_confidence: float = 0.8) -> list[str]:
    """Medicine names the NER model finds in readable text that match none of the listed lines.
    Used only to WARN the user ("this page may also mention X"); nothing is added to the list automatically."""
    from difflib import SequenceMatcher

    ner = ner or default_ner()
    listed = [re.sub(r"[^a-z0-9]+", "", n.lower()) for n in listed_names if n]
    found = []
    for e in ner.extract(text, min_confidence=min_confidence):
        name = e.text.strip(" .,:;()")
        key = re.sub(r"[^a-z0-9]+", "", name.lower())
        if e.category != "medication" or len(key) < 4 or not re.search(r"[a-z]{3}", key):
            continue
        if any(key in item or item in key or SequenceMatcher(None, key, item).ratio() >= 0.6 for item in listed if item):
            continue
        if key not in [re.sub(r"[^a-z0-9]+", "", f.lower()) for f in found]:
            found.append(name)
    return found
