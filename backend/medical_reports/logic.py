"""Small, testable helpers shared by report views: range comparison and reference-range parsing."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUM = r"\d+(?:[.,]\d+)?"
_RANGE = re.compile(rf"(?P<lo>{_NUM})\s*(?:-|–|to)\s*(?P<hi>{_NUM})|"
                    rf"(?P<op>[<>≤≥]=?|up\s*to|upto|below|less\s+than|under|above|more\s+than|greater\s+than|over)"
                    rf"\s*(?P<v>{_NUM})", re.I)


def to_decimal(text) -> Decimal | None:
    if text in (None, ""):
        return None
    m = re.search(_NUM, str(text))
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", "."))
    except InvalidOperation:
        return None


def parse_range(text: str) -> tuple[Decimal | None, Decimal | None]:
    m = _RANGE.search(text or "")
    if not m:
        return None, None
    if m.group("lo"):
        return to_decimal(m.group("lo")), to_decimal(m.group("hi"))
    op = re.sub(r"\s+", "", m.group("op").lower())
    v = to_decimal(m.group("v"))
    return (None, v) if op in ("<", "<=", "≤", "upto", "below", "lessthan", "under") else (v, None)


def range_status(value, low, high) -> str:
    """AyuMitra's comparison with the *laboratory's printed* range. The lab's own flag is separate."""
    if value is None or (low is None and high is None):
        return "unknown"
    if low is not None and value < low:
        return "below"
    if high is not None and value > high:
        return "above"
    return "within"


_RANGED_VALUE = re.compile(rf"^\s*({_NUM})\s*-\s*({_NUM})\b")


def _norm_word(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def owner_sex(param) -> str:
    """'male' / 'female' from the report owner's profile, '' if not set (then nothing sex-specific is compared)."""
    try:
        sex = param.report.document.owner.patient_profile.sex
    except Exception:  # noqa: BLE001 - no profile yet
        return ""
    return sex if sex in ("male", "female") else ""


def typical_range(param, sex: str | None = None) -> dict | None:
    """Cited typical range for a result whose report printed none (stored at processing time).

    Returns {"selected": <range or None>, "options": [...]}: 'selected' is the one that applies (sex-neutral,
    or matching the profile's sex). A range the lab printed always wins, so this is None whenever the
    result has its own reference text."""
    if (param.reference_range_text or "").strip() or param.reference_low is not None or param.reference_high is not None:
        return None
    options = ((param.report.raw or {}).get("typical_ranges") or {}).get(str(param.pk)) or []
    if not options:
        return None
    sex = owner_sex(param) if sex is None else sex
    selected = next((o for o in options if o.get("sex") == "any"), None) or \
        next((o for o in options if sex and o.get("sex") == sex), None)
    return {"selected": selected, "options": options}


def _typical_status(param, rng: dict | None) -> str:
    if not rng or not rng.get("comparable") or param.value_numeric is None:
        return "unknown"
    value = param.value_numeric
    low, high = to_decimal(rng.get("low")), to_decimal(rng.get("high"))
    if low is not None and (value < low if rng.get("low_inclusive", True) else value <= low):
        return "below"
    if high is not None and (value > high if rng.get("high_inclusive", True) else value >= high):
        return "above"
    return "within"


def range_info(param, sex: str | None = None) -> dict:
    """{"status", "source": "lab" | "typical" | "", "typical": typical_range(...) or None}."""
    status = param_range_status(param)
    if status != "unknown":
        return {"status": status, "source": "lab", "typical": None}
    typ = typical_range(param, sex)
    if typ:
        return {"status": _typical_status(param, typ["selected"]), "source": "typical", "typical": typ}
    return {"status": "unknown", "source": "", "typical": None}


def param_range_status(param) -> str:
    """Status for one stored result, covering every way a lab prints a value:

    - a number ("6.0" vs "4.5-8")              -> below / within / above
    - a ranged count ("2-3 /hpf" vs "0-5")      -> both ends compared: within only if both are inside
    - a word ("Negative" vs "Negative")         -> "matches" if identical to the printed reference,
                                                   "differs" otherwise (never interpreted further)
    - anything else                              -> "unknown"
    """
    low, high = param.reference_low, param.reference_high
    if param.value_numeric is not None:
        return range_status(param.value_numeric, low, high)
    m = _RANGED_VALUE.match(param.value_text or "")
    if m and (low is not None or high is not None):
        ends = {range_status(to_decimal(m.group(1)), low, high), range_status(to_decimal(m.group(2)), low, high)}
        for s in ("above", "below", "unknown"):
            if s in ends:
                return s
        return "within"
    value, ref = _norm_word(param.value_text), _norm_word(param.reference_range_text)
    if value and ref and not re.search(r"\d", value + ref):
        return "matches" if value == ref else "differs"
    return "unknown"


def parameter_context(param) -> dict:
    """What the AI service may see about one of the user's own results (for retrieval steering)."""
    info = range_info(param)
    return {
        "name_as_printed": param.name_as_printed,
        "normalized_name": param.normalized_name,
        "value_text": param.value_text,
        "unit": param.unit,
        "reference_range_text": param.reference_range_text or _typical_text(info),
        "lab_flag": param.lab_flag,
        "range_status": info["status"],
        "range_source": info["source"],
    }


def _typical_text(info: dict) -> str:
    sel = (info.get("typical") or {}).get("selected")
    if not sel or info["source"] != "typical":
        return ""
    return f"{sel['display']} (typical adult range from {sel['publisher']}; not printed by the lab)"
