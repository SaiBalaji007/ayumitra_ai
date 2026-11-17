"""Small, testable helpers shared by report views: range comparison and reference-range parsing."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUM = r"\d+(?:[.,]\d+)?"
_RANGE = re.compile(rf"(?P<lo>{_NUM})\s*(?:-|–|to)\s*(?P<hi>{_NUM})|(?P<op>[<>≤≥]=?|up\s*to|upto)\s*(?P<v>{_NUM})", re.I)


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
    op = m.group("op").lower().replace(" ", "")
    v = to_decimal(m.group("v"))
    return (None, v) if op in ("<", "<=", "≤", "upto") else (v, None)


def range_status(value, low, high) -> str:
    """AyuMitra's comparison with the *laboratory's printed* range. The lab's own flag is separate."""
    if value is None or (low is None and high is None):
        return "unknown"
    if low is not None and value < low:
        return "below"
    if high is not None and value > high:
        return "above"
    return "within"


def parameter_context(param) -> dict:
    """What the AI service may see about one of the user's own results (for retrieval steering)."""
    return {
        "name_as_printed": param.name_as_printed,
        "normalized_name": param.normalized_name,
        "value_text": param.value_text,
        "unit": param.unit,
        "reference_range_text": param.reference_range_text,
        "lab_flag": param.lab_flag,
        "range_status": range_status(param.value_numeric, param.reference_low, param.reference_high),
    }
