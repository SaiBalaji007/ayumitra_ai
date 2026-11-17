"""
Laboratory result extraction from report text, PDF tables or OCR rows.

Each result keeps exactly what the laboratory printed: name, value text, unit, reference interval
and flag. Parsed fields (numeric value, bounds, canonical unit, normalised test name) are added
next to them. The *lab's* flag is kept separate from AyuMitra's own comparison against the
printed range (`range_status`). Nothing is filled in when absent.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

from .units import UNIT_PATTERN, normalize_unit

# Printed-name aliases -> normalised name. Spelling variants only; this is not medical knowledge.
TEST_ALIASES: dict[str, list[str]] = {
    "hemoglobin": ["haemoglobin", "hemoglobin", "hb", "hgb"],
    "hba1c": ["hba1c", "glycated haemoglobin", "glycated hemoglobin", "glycosylated haemoglobin", "a1c"],
    "glucose_fasting": ["fasting blood sugar", "fasting blood glucose", "fbs", "fasting plasma glucose", "glucose fasting", "blood sugar fasting",
                        "fasting glucose"],
    "glucose_postprandial": ["post prandial blood sugar", "ppbs", "postprandial glucose", "blood sugar pp"],
    "glucose_random": ["random blood sugar", "rbs", "glucose random"],
    "wbc": ["total wbc count", "wbc", "total leucocyte count", "tlc", "white blood cells", "total leukocyte count"],
    "rbc": ["rbc count", "total rbc count", "red blood cells", "rbc"],
    "platelets": ["platelet count", "platelets", "plt"],
    "creatinine": ["serum creatinine", "creatinine", "s. creatinine"],
    "urea": ["blood urea", "urea", "serum urea"],
    "bun": ["blood urea nitrogen", "bun"],
    "uric_acid": ["uric acid", "serum uric acid", "s. uric acid"],
    "cholesterol_total": ["total cholesterol", "cholesterol total", "serum cholesterol", "cholesterol"],
    "hdl": ["hdl cholesterol", "hdl", "hdl-c"],
    "ldl": ["ldl cholesterol", "ldl", "ldl-c", "ldl cholesterol direct"],
    "triglycerides": ["triglycerides", "triglyceride", "tg"],
    "alt": ["sgpt", "alt", "sgpt (alt)", "alanine aminotransferase", "alanine transaminase"],
    "ast": ["sgot", "ast", "sgot (ast)", "aspartate aminotransferase"],
    "bilirubin_total": ["total bilirubin", "bilirubin total", "serum bilirubin"],
    "tsh": ["tsh", "thyroid stimulating hormone", "tsh ultrasensitive"],
    "t3": ["t3", "total t3", "triiodothyronine"],
    "t4": ["t4", "total t4", "thyroxine"],
    "vitamin_d": ["vitamin d", "vitamin d (25-oh)", "25-oh vitamin d", "25 hydroxy vitamin d", "vitamin d3", "vit d"],
    "vitamin_b12": ["vitamin b12", "vit b12", "cyanocobalamin"],
    "ferritin": ["ferritin", "serum ferritin"],
    "sodium": ["sodium", "na+", "serum sodium"],
    "potassium": ["potassium", "k+", "serum potassium"],
    "esr": ["esr", "erythrocyte sedimentation rate"],
    "hematocrit": ["haematocrit", "hematocrit", "pcv", "hct", "packed cell volume", "haematocrit (pcv)", "hematocrit (pcv)"],
    "mcv": ["mcv", "mean corpuscular volume", "mean cell volume"],
    "crp": ["crp", "c-reactive protein", "c reactive protein", "crp (c-reactive protein)"],
}
_ALIAS_INDEX = {alias: norm for norm, aliases in TEST_ALIASES.items() for alias in aliases}

# Characters OCR commonly confuses, folded to one form so "HbAlc" can still be recognised as "HbA1c".
_OCR_FOLD = str.maketrans({"1": "l", "i": "l", "|": "l", "0": "o"})


def _ocr_fold(text: str) -> str:
    return text.translate(_OCR_FOLD)


_FOLDED_INDEX: dict[str, str] = {}
for _alias, _norm in _ALIAS_INDEX.items():
    _FOLDED_INDEX.setdefault(_ocr_fold(_alias), _norm)
OCR_FOLD_CONFIDENCE = 0.75  # below the 0.8 review threshold: such rows are always shown for checking


def normalize_test_name(name: str) -> tuple[str, float]:
    """(normalised_name, match_confidence). Unknown names keep their own slug at lower confidence."""
    key = re.sub(r"\s+", " ", name.lower().strip(" :.-*"))
    if key in _ALIAS_INDEX:
        return _ALIAS_INDEX[key], 1.0
    stripped = re.sub(r"\(.*?\)", "", key).strip()
    if stripped in _ALIAS_INDEX:
        return _ALIAS_INDEX[stripped], 0.95
    for candidate in (key, stripped):
        if _ocr_fold(candidate) in _FOLDED_INDEX:
            return _FOLDED_INDEX[_ocr_fold(candidate)], OCR_FOLD_CONFIDENCE
    return re.sub(r"[^a-z0-9]+", "_", key).strip("_"), 0.5


_NUM = r"\d+(?:[.,]\d+)?"
_UPPER_WORDS = ("below", "less than", "under", "lessthan")
_LOWER_WORDS = ("above", "more than", "greater than", "over", "morethan", "greaterthan")
_WORD_OPS = r"below|less\s+than|under|above|more\s+than|greater\s+than|over"
_RANGE = re.compile(
    rf"(?P<lo>{_NUM})\s*(?:-|–|to)\s*(?P<hi>{_NUM})|(?P<op>[<>≤≥]=?|up\s*to|upto|{_WORD_OPS})\s*(?P<v>{_NUM})",
    re.IGNORECASE,
)
_VALUE = re.compile(rf"^(?P<op>[<>]=?)?\s*(?P<num>{_NUM})$|^(?P<qual>positive|negative|reactive|non[- ]reactive|nil|absent|present|trace)$", re.I)
_FLAG = re.compile(r"^(h|l|high|low|\*|hh|ll|critical|abnormal)$", re.I)

FLAG_MAP = {"h": "high", "high": "high", "hh": "critical_high", "l": "low", "low": "low", "ll": "critical_low",
            "*": "abnormal", "abnormal": "abnormal", "critical": "abnormal"}


@dataclass
class LabResult:
    name_as_printed: str
    normalized_name: str
    value_text: str
    value_numeric: str | None       # Decimal as string, for JSON
    unit: str
    unit_canonical: str | None
    reference_range_text: str
    reference_low: str | None
    reference_high: str | None
    lab_flag: str                   # as printed by the lab, normalised label ("" if none)
    range_status: str               # AyuMitra's comparison with the printed range: below|within|above|unknown
    confidence: float
    needs_review: bool
    issues: list[str] = field(default_factory=list)
    source_line: str = ""
    page: int | None = None

    def to_dict(self):
        return asdict(self)


def _dec(s: str | None) -> Decimal | None:
    if s is None:
        return None
    try:
        return Decimal(s.replace(",", "."))
    except InvalidOperation:
        return None


def parse_range(text: str) -> tuple[Decimal | None, Decimal | None]:
    m = _RANGE.search(text)
    if not m:
        return None, None
    if m.group("lo"):
        return _dec(m.group("lo")), _dec(m.group("hi"))
    op, v = re.sub(r"\s+", "", m.group("op").lower()), _dec(m.group("v"))
    if op in ("<", "<=", "≤", "upto", "lessthan", "below", "under"):
        return None, v
    return v, None


def compare(value: Decimal | None, lo: Decimal | None, hi: Decimal | None) -> str:
    if value is None or (lo is None and hi is None):
        return "unknown"
    if lo is not None and value < lo:
        return "below"
    if hi is not None and value > hi:
        return "above"
    return "within"


# Word results, mostly from urine/stool examinations ("Colour  Pale Yellow", "Pus cells  Occasional").
_QUAL = (r"(?:non[- ]reactive|reactive|positive|negative|nil|absent|present|trace|occasional|normal|clear|"
         r"slightly\s+turbid|turbid|hazy|pale\s+yell?ow|straw\s+yell?ow|dark\s+yell?ow|yell?ow|amber|colou?rless|[1-4]\+)")

def _compare_range_value(value_text: str, lo: Decimal | None, hi: Decimal | None) -> str:
    """A ranged count ("2-3" cells) is within only if both ends are; above/below if either end is outside."""
    a, b = (_dec(x.strip()) for x in value_text.split("-", 1))
    if a is None or b is None:
        return "unknown"
    statuses = {compare(a, lo, hi), compare(b, lo, hi)}
    for s in ("above", "below", "unknown"):
        if s in statuses:
            return s
    return "within"


_ROW = re.compile(
    rf"^(?P<name>[A-Za-z][A-Za-z0-9 ().,/+'-]*?[A-Za-z0-9)])\s*[:]?\s+"
    # A count printed as a range ("Pus cells 2-3 /hpf  0-5") is a value only when a reference range follows;
    # parse_line enforces that, so a printed reference range is never mistaken for the result.
    rf"(?P<value>(?P<vrange>{_NUM}\s*-\s*{_NUM})|[<>]=?\s*{_NUM}|{_NUM}|(?P<vqual>{_QUAL}))"
    rf"(?(vqual)(?:\s+(?P<qref>{_QUAL}))?)"  # word result with a word reference ("Negative  Negative")
    rf"(?:\s+(?P<flag>H|L|HH|LL|High|Low|\*))?"
    rf"(?:\s+(?P<status>normal|nomal|noma|norm|borderline|within\s+limits|wnl))?"
    # An unreadable unit ("mg/dL" scanned as "7p/3w") still occupies the unit column: keep it as printed
    # (flagged), so the value and range around it are captured correctly instead of being misaligned.
    rf"(?:\s+(?:(?P<unit>{UNIT_PATTERN.pattern})|(?P<badunit>[A-Za-z0-9µ]{{1,4}}/[A-Za-z0-9µ]{{1,4}})))?"
    rf"(?:\s+(?P<flag2>H|L|High|Low|\*))?"
    rf"(?:\s+(?P<range>(?:[<>≤≥]=?|up\s*to|upto|{_WORD_OPS})?\s*{_NUM}\s*(?:(?:-|–|to)\s*{_NUM})?))?"
    rf"(?:\s*(?P<unit2>{UNIT_PATTERN.pattern}))?"
    rf"(?:\s+(?P<flag3>H|L|HH|LL|High|Low|Critical|Abnormal))?\s*$",  # "Flag" column after the range
    re.IGNORECASE,
)


_TRAILING_WORD = re.compile(r"[A-Za-z][A-Za-z'()./:-]*")
MAX_TRAILING_WORDS = 5


def _match_row(clean: str):
    """Match a result row. Many labs add a "Methodology" column after the range ("... 4.5-8  pH Indicators");
    up to five trailing words are dropped, but only if what remains still has a unit or a reference
    (numeric range or word), so header or prose lines are never turned into results."""
    m = _valid(_ROW.match(clean))
    if m:
        return m
    tokens = clean.split(" ")
    for cut in range(1, min(MAX_TRAILING_WORDS, len(tokens) - 2) + 1):
        if not _TRAILING_WORD.fullmatch(tokens[-cut]):
            break
        m = _valid(_ROW.match(" ".join(tokens[:-cut])))
        if m and (m.group("range") or m.group("qref") or m.group("unit") or m.group("unit2")):
            return m
    return None


def _valid(m):
    """A ranged value ("2-3") with no reference range after it is really the reference range itself
    ("13.0-17.0", or "...72 H U/L 7-56" with the name glued to its value): not a result row."""
    if m and m.group("vrange") and not (m.group("range") or "").strip():
        return None
    # A "name" holding a bare number or a unit ("HDL Cholesterol 46 mg/dL Above" with value "40") means the
    # pattern swallowed the real value: reject this reading so a shorter, correct one can be tried.
    if m and _NAME_HAS_VALUE(m.group("name")):
        return None
    return m


_LAYOUT_WORDS = {"page", "pages", "bed", "bed no", "ward", "room", "below", "above", "under", "over", "less than",
                 "more than", "sample", "sample no", "lab", "lab no", "report", "report no", "age", "no", "sr", "sr no",
                 "s no", "sl", "sl no", "serial no", "token", "token no", "visit", "visit no", "reg no", "id"}


def _NAME_HAS_VALUE(name: str) -> bool:
    return any(re.fullmatch(r"\d+(?:[.,]\d+)?", t) or ("/" in t and re.search(r"\d", t)) for t in name.split())


def parse_line(line: str, *, page: int | None = None, ocr_confidence: float | None = None) -> LabResult | None:
    clean = re.sub(r"\s{2,}|\t|\|", "  ", line).strip()
    clean = re.sub(r"\s+", " ", clean)
    # Accreditation/footnote marks glued to a test name ("Colour*", "Reaction (pH)*") are not part of it;
    # a standalone "*" (a flag column) is left alone.
    clean = re.sub(r"(?<=[A-Za-z0-9)])\*+(?=\s|$)", "", clean)
    clean = re.sub(r"(?:(?<=[A-Za-z]{3})|(?<=\)))[.'\"`]+(?=\s)", "", clean)  # the same mark as OCR misreads it
    m = _match_row(clean)
    glued = False
    if not m:
        # OCR sometimes drops the space between the test name and its value ("HbAlc3.6 L % 4.0 - 5.6").
        # Only split when the letters before the number are a known test name, so names that end in a
        # digit ("T3", "Vitamin B12") are never cut apart.
        g = re.match(r"^([A-Za-z][A-Za-z ()/-]*[A-Za-z)])(?=\d)", clean)
        if g and normalize_test_name(g.group(1))[1] >= OCR_FOLD_CONFIDENCE:
            m, glued = _valid(_ROW.match(g.group(1) + " " + clean[g.end():])), True
    if not m:
        return None
    name = m.group("name").strip()
    # Safety: a test name never contains a bare number or a digit-and-slash token. If it does, the
    # value column was misread ("Total Cholesterol 7p/8w < 200") and the "value" would really be the
    # reference range. Skipping the row is safe; reporting the range as the result is not.
    if any(re.fullmatch(r"\d+(?:[.,]\d+)?", t) or ("/" in t and re.search(r"\d", t)) for t in name.split()):
        return None
    norm, name_conf = normalize_test_name(name)
    if name_conf < 1.0 and len(name) < 3:
        return None
    if m.group("vqual") and norm in TEST_ALIASES:
        # Known names here are blood tests with numeric results. A word result ("Red blood cells  Absent")
        # comes from urine/stool microscopy: keep it apart so it never joins the blood count's history.
        norm = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    value_text = re.sub(r"\s+", " ", m.group("value").strip())
    # Barcodes, phone numbers and IDs in report headers look like "NAME 01234567890". No lab value
    # has more than 8 integer digits (RBC counts are ~7), so such lines are not results.
    if len(re.sub(r"[^0-9]", "", value_text.split(".")[0].split(",")[0])) > 8:
        return None
    num_m = _VALUE.match(value_text.replace(" ", ""))
    numeric = _dec(num_m.group("num")) if num_m and num_m.group("num") else None
    unit_text = (m.group("unit") or m.group("badunit") or m.group("unit2") or "").strip()
    # An unrecognised name with no unit, no range and a long ID-like number is header text
    # ("UHID 556123", "Lab No 004512"), not a result. Short values ("Glucose 92", "HBsAg Negative") stay.
    digits = len(re.sub(r"[^0-9]", "", value_text))
    if name_conf < OCR_FOLD_CONFIDENCE and not unit_text and not (m.group("range") or "").strip() and digits >= 6:
        return None
    # Page furniture with a bare number ("Page 1", "Below 200", "Bed 12") is not a result either.
    if (name.lower().strip(" .:#") in _LAYOUT_WORDS and numeric is not None and not unit_text
            and not (m.group("range") or "").strip()):
        return None
    unit = normalize_unit(unit_text) if unit_text else None
    range_text = (m.group("range") or "").strip()
    lo, hi = parse_range(range_text) if range_text else (None, None)
    range_unreadable = lo is not None and hi is not None and lo > hi  # e.g. "4.5-8" scanned as "45-8"
    if range_unreadable:
        lo = hi = None
    qref = re.sub(r"\s+", " ", (m.group("qref") or "").strip())
    if qref and not range_text:
        range_text = qref  # word reference ("Negative") is the printed reference interval
    flag_raw = (m.group("flag") or m.group("flag2") or m.group("flag3") or "").strip()
    lab_flag = FLAG_MAP.get(flag_raw.lower(), "") if flag_raw else ""

    issues = []
    conf = name_conf
    if not unit_text:
        issues.append("no unit printed")
        conf *= 0.9
    elif unit and not unit.known:
        issues.append("unrecognised unit")
        conf *= 0.85
        if m.group("badunit"):  # unit unreadable in the scan: always ask the user to check this row
            issues.append("the unit could not be read; please check it against your report")
            conf = min(conf, 0.7)
    if range_unreadable:
        issues.append("the reference range could not be read correctly; please check it against your report")
        conf = min(conf, 0.7)
    if not range_text:
        issues.append("no reference range printed")
        conf *= 0.95
    if name_conf == OCR_FOLD_CONFIDENCE:
        issues.append("test name recognised only after correcting likely scan misreads (such as l for 1); please check")
    elif name_conf < 1.0:
        issues.append("test name not in the known alias list")
    if glued:
        issues.append("the value was joined to the test name in the scan; please check")
        conf = min(conf, 0.75)
    if ocr_confidence is not None:
        conf *= ocr_confidence
    conf = round(conf, 3)
    return LabResult(
        name_as_printed=name, normalized_name=norm, value_text=value_text,
        value_numeric=str(numeric) if numeric is not None else None, unit=unit_text,
        unit_canonical=unit.canonical if unit else None, reference_range_text=range_text,
        reference_low=str(lo) if lo is not None else None, reference_high=str(hi) if hi is not None else None,
        lab_flag=lab_flag,
        # Word results are only called "within" when they literally match the printed reference; any other
        # word ("Positive" vs "Negative") stays "unknown" rather than AyuMitra guessing its meaning.
        range_status=("within" if qref and value_text.lower() == qref.lower() else "unknown") if m.group("vqual")
        else _compare_range_value(value_text, lo, hi) if m.group("vrange") else compare(numeric, lo, hi),
        confidence=conf,
        needs_review=conf < 0.8 or (ocr_confidence is not None and ocr_confidence < 0.85),
        issues=issues, source_line=line.strip(), page=page,
    )


def extract_lab_results(lines: list[str], *, page: int | None = None,
                        line_confidences: list[float | None] | None = None) -> list[LabResult]:
    results, seen = [], set()
    for i, line in enumerate(lines):
        conf = line_confidences[i] if line_confidences else None
        r = parse_line(line, page=page, ocr_confidence=conf)
        if r is None:
            continue
        key = (r.normalized_name, r.value_text, r.unit)
        if key in seen:
            continue
        seen.add(key)
        results.append(r)
    return results


def extract_from_table(rows: list[list[str]], *, page: int | None = None) -> list[LabResult]:
    """Table rows (from PDF table detection or OCR row grouping) are joined and parsed as lines."""
    return extract_lab_results(["  ".join(c for c in row if c) for row in rows], page=page)
