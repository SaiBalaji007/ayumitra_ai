"""
Typical adult reference ranges for results whose report printed no range (knowledge/reference_ranges.json).

Every range is quoted from a public-domain source in the library (tests verify each quote). They are
offered only as "typical", never as the laboratory's range, and only when the result's unit matches the
range's unit exactly: a CRP in mg/L is never compared with a range in mg/dL. Sex-specific ranges are all
returned; the backend picks one from the user's profile and compares nothing if sex is unknown.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .nlp.units import normalize_unit

TABLE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "reference_ranges.json"


@lru_cache(maxsize=1)
def load_table() -> list[dict]:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))["ranges"]


@lru_cache(maxsize=1)
def _sources() -> dict[str, dict]:
    path = TABLE_PATH.parent / "sources.json"
    return {s["id"]: s for s in json.loads(path.read_text(encoding="utf-8"))["sources"]}


def typical_ranges(normalized_name: str, unit_printed: str) -> list[dict]:
    """Typical ranges for one result, each with its source and whether it can be compared (same unit)."""
    rows = [r for r in load_table() if r["test"] == normalized_name]
    if not rows:
        return []
    unit = normalize_unit(unit_printed).canonical if unit_printed else None
    out = []
    for r in rows:
        src = _sources().get(r["source_id"], {})
        out.append({
            "sex": r["sex"], "low": r.get("low"), "high": r.get("high"),
            "low_inclusive": r.get("low_inclusive", True), "high_inclusive": r.get("high_inclusive", True),
            "unit": r["unit"], "display": r["display"], "comparable": unit is not None and unit == r["unit"],
            "quote": r["quote"], "source_id": r["source_id"], "source_title": src.get("title", ""),
            "publisher": src.get("publisher", ""), "url": src.get("url", ""),
        })
    return out
