"""
Prescription line extraction: form, medicine, strength, dose, frequency, timing, duration, route.

Fields are captured AS WRITTEN. A field that isn't on the prescription stays empty: no dose,
frequency or duration is ever inferred. Per-field confidence combines OCR confidence with
pattern certainty, and uncertain fields are listed in `fields_needing_review` for the user.
Frequency shorthands (BD, 1-0-1, ...) get a plain-language *reading* next to the written text.
These are standard abbreviations, not clinical advice.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .medicines import MedicineMatch, RxNormLexicon

FORMS = {
    "tab": "tablet", "tabs": "tablet", "tablet": "tablet", "cap": "capsule", "caps": "capsule", "capsule": "capsule",
    "syp": "syrup", "syr": "syrup", "syrup": "syrup", "inj": "injection", "injection": "injection",
    "oint": "ointment", "cream": "cream", "drops": "drops", "drop": "drops", "gel": "gel", "susp": "suspension",
    "sachet": "sachet", "inh": "inhaler", "inhaler": "inhaler",
}
FREQUENCY_READING = {
    "od": "once a day", "qd": "once a day", "bd": "twice a day", "bid": "twice a day", "tds": "three times a day",
    "tid": "three times a day", "qid": "four times a day", "hs": "at bedtime", "sos": "only when needed",
    "prn": "only when needed", "stat": "immediately, once", "weekly": "once a week", "daily": "once a day",
}
_FREQ_TOKEN = re.compile(r"\b(od|qd|bd|bid|tds|tid|qid|hs|sos|prn|stat|weekly|daily|once daily|twice daily)\b", re.I)
_FREQ_PATTERN = re.compile(r"(?<![\d.])([0-4](?:\s*[-–]\s*[0-4]){2,3})(?![\d.])")  # 1-0-1, 1-1-1-1
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?\s*(?:mg|mcg|µg|g|ml|iu|units?|%)(?:\s*/\s*\d*\s*(?:ml|g))?)\b", re.I)
_DURATION = re.compile(r"(?:x|for|×)\s*(\d+\s*(?:days?|weeks?|months?|d|wk|wks))\b|\b(\d+\s*(?:days?|weeks?|months?))\b", re.I)
_TIMING = re.compile(r"\b(after (?:food|meals?|breakfast|lunch|dinner)|before (?:food|meals?|breakfast|lunch|dinner)|"
                     r"with (?:food|meals?|milk|water)|empty stomach|at (?:bed ?time|night)|in the (?:morning|evening|night)|"
                     r"ac|pc)\b", re.I)
_ROUTE = re.compile(r"\b(oral(?:ly)?|po|iv|im|sc|subcutaneous|topical|inhal\w*|nasal|eye|ear)\b", re.I)
_FORM = re.compile(r"^\s*(?:\d+[.)]\s*)?(" + "|".join(sorted(FORMS, key=len, reverse=True)) + r")\.?\s+", re.I)
_FREQ_WORDS = r"od|qd|bd|bid|tds|tid|qid|hs|sos|prn|stat|weekly|daily|once daily|twice daily"
# Up to three words ("Vitamin D3", "Amoxicillin Clavulanate"), ending before a number or a frequency word.
_NAME = re.compile(rf"^([A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*){{0,2}}?)(?=\s+\d|\s*$|\s+(?:{_FREQ_WORDS})\b)", re.I)


@dataclass
class PrescriptionItem:
    line_number: int
    source_line: str
    dosage_form: str = ""
    name_as_written: str = ""
    strength: str = ""
    frequency: str = ""
    frequency_reading: str = ""
    timing: str = ""
    duration: str = ""
    route: str = ""
    medicine: dict | None = None
    field_confidence: dict = field(default_factory=dict)
    overall_confidence: float = 0.0
    fields_needing_review: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def read_frequency(freq: str) -> str:
    f = freq.lower().strip()
    if f in FREQUENCY_READING:
        return FREQUENCY_READING[f]
    if _FREQ_PATTERN.fullmatch(f.replace(" ", "")):
        parts = [int(p) for p in re.split(r"[-–]", f.replace(" ", ""))]
        slots = ["morning", "afternoon", "night"] if len(parts) == 3 else ["morning", "afternoon", "evening", "night"]
        taken = [f"{n} in the {s}" for n, s in zip(parts, slots, strict=True) if n]
        return ", ".join(taken) if taken else ""
    return ""


def is_medication_line(line: str) -> bool:
    return bool(_FORM.match(line)) or bool(_STRENGTH.search(line) and (_FREQ_TOKEN.search(line) or _FREQ_PATTERN.search(line)))


def parse_item(line: str, line_number: int, lexicon: RxNormLexicon | None, ocr_confidence: float | None = None) -> PrescriptionItem:
    item = PrescriptionItem(line_number=line_number, source_line=line.strip())
    rest = line.strip()
    base = 1.0 if ocr_confidence is None else ocr_confidence

    if m := _FORM.match(rest):
        item.dosage_form = FORMS[m.group(1).lower()]
        rest = rest[m.end():]
    else:
        rest = re.sub(r"^\s*\d+[.)]\s*", "", rest)
    rest = rest.lstrip(" .:-,;")  # OCR noise between the form and the name: "Tab  .Daotun"

    if m := _NAME.match(rest):
        item.name_as_written = m.group(1).strip()
    if m := _STRENGTH.search(rest):
        item.strength = re.sub(r"\s+", " ", m.group(1)).strip()
    if m := _FREQ_PATTERN.search(rest):
        item.frequency = re.sub(r"\s+", "", m.group(1))
    elif m := _FREQ_TOKEN.search(rest):
        item.frequency = m.group(1)
    item.frequency_reading = read_frequency(item.frequency) if item.frequency else ""
    if m := _TIMING.search(rest):
        item.timing = m.group(1)
    if m := _DURATION.search(rest):
        item.duration = (m.group(1) or m.group(2)).strip()
    if m := _ROUTE.search(rest):
        item.route = m.group(1)

    match: MedicineMatch | None = lexicon.match(item.name_as_written) if (lexicon and item.name_as_written) else None
    if match:
        item.medicine = match.to_dict()

    name_conf = 0.0
    if item.name_as_written:
        name_conf = 1.0 if match and match.status.startswith("exact") else 0.6 if match and match.status == "suggestion" else 0.5
    conf = {
        "name": round(base * name_conf, 3),
        "strength": round(base * (0.95 if item.strength else 0.0), 3),
        "frequency": round(base * (0.95 if item.frequency else 0.0), 3),
        "timing": round(base * (0.9 if item.timing else 0.0), 3),
        "duration": round(base * (0.95 if item.duration else 0.0), 3),
    }
    item.field_confidence = conf
    for f in ("name", "strength", "frequency", "duration"):
        if conf[f] < 0.85:
            item.fields_needing_review.append(f)  # missing or uncertain: the user must check, nothing is filled in
    present = [conf[f] for f in conf if conf[f] > 0]
    item.overall_confidence = round(min(present) if present else 0.0, 3)
    return item


_FORM_ONLY = re.compile(r"^\s*(?:\d+[.)]\s*)?(" + "|".join(sorted(FORMS, key=len, reverse=True)) + r")\.?\s*$", re.I)
_FREQ_ONLY = re.compile(r"^\s*(?:" + _FREQ_PATTERN.pattern + r"|" + _FREQ_TOKEN.pattern + r")(?:\s+" + _TIMING.pattern + r")?\s*$", re.I)


def _min_conf(a, b):
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None


def extract_prescription(lines: list[str], lexicon: RxNormLexicon | None = None,
                         line_confidences: list[float | None] | None = None) -> list[PrescriptionItem]:
    """One item per medicine line. Handles how OCR splits handwritten prescriptions:
    - "Tab" alone on a line followed by the name on the next line -> one line;
    - a frequency-only line ("BD", "1-0-1") directly below a medicine -> that medicine's frequency.
    Nothing is guessed: names stay as read and are flagged for the user to confirm."""
    confs = list(line_confidences) if line_confidences else [None] * len(lines)
    items: list[PrescriptionItem] = []
    item_text: dict[int, str] = {}   # item index -> the text it was parsed from
    last_item_line = -2              # index (in `lines`) of the line that produced the last item
    i = 0
    while i < len(lines):
        line, conf = lines[i], confs[i]
        if _FORM_ONLY.match(line) and i + 1 < len(lines) and lines[i + 1].strip() \
                and not is_medication_line(lines[i + 1]) and not _FREQ_ONLY.match(lines[i + 1]):
            line, conf = f"{line.strip()} {lines[i + 1].strip()}", _min_conf(conf, confs[i + 1])
            i += 1
        if is_medication_line(line):
            items.append(parse_item(line, len(items) + 1, lexicon, conf))
            item_text[len(items) - 1] = line
            last_item_line = i
        elif _FREQ_ONLY.match(line) and items and last_item_line == i - 1 and not items[-1].frequency:
            text = f"{item_text[len(items) - 1]} {line.strip()}"
            items[-1] = parse_item(text, items[-1].line_number, lexicon, _min_conf(conf, items[-1].field_confidence and None))
            item_text[len(items) - 1] = text
            last_item_line = i
        i += 1
    return items
