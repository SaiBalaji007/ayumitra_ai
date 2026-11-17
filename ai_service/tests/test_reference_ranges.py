"""Typical reference ranges: every number must be quoted from the library, and only same-unit results compare."""
import re
import sqlite3
from decimal import Decimal

import pytest

from ayumitra_ai.config import get_settings
from ayumitra_ai.nlp.lab_extraction import TEST_ALIASES
from ayumitra_ai.reference_ranges import _sources, load_table, typical_ranges


def _library_text(source_id: str) -> str | None:
    db = get_settings().data_dir / "knowledge.sqlite3"
    if not db.exists():
        return None
    with sqlite3.connect(db) as c:
        rows = c.execute("select text from sections where source_id=? order by ord", (source_id,)).fetchall()
    return " ".join(" ".join(t.split()) for (t,) in rows) or None


@pytest.mark.parametrize("row", load_table(), ids=lambda r: f"{r['test']}-{r['sex']}")
def test_every_range_is_quoted_from_the_library(row):
    assert row["source_id"] in _sources(), "source must be listed in knowledge/sources.json"
    text = _library_text(row["source_id"])
    if text is None:
        pytest.skip("knowledge library not ingested on this machine")
    assert row["quote"] in text, "quote must appear word for word in the ingested source"
    # each bound must literally appear in the quote: no number may come from anywhere else
    for bound in (row.get("low"), row.get("high")):
        if bound is not None:
            assert re.search(rf"(?<![\d.]){re.escape(bound)}(?![\d])", row["quote"]), bound


@pytest.mark.parametrize("row", load_table(), ids=lambda r: f"{r['test']}-{r['sex']}")
def test_table_rows_are_well_formed(row):
    assert row["test"] in TEST_ALIASES, "test must be a normalised name the extractor produces"
    assert row["sex"] in ("any", "male", "female")
    assert row.get("low") is not None or row.get("high") is not None
    if row.get("low") is not None and row.get("high") is not None:
        assert Decimal(row["low"]) < Decimal(row["high"])


def test_only_matching_units_are_comparable():
    (crp,) = typical_ranges("crp", "mg/dL")
    assert crp["comparable"] and crp["high"] == "1.0" and "MedlinePlus" in crp["publisher"]
    assert not typical_ranges("crp", "mg/L")[0]["comparable"]  # 10x different unit: never compared
    assert not typical_ranges("crp", "")[0]["comparable"]       # no unit printed: never compared


def test_sex_specific_ranges_returned_together():
    rows = typical_ranges("hemoglobin", "gm/dL")
    assert {r["sex"] for r in rows} == {"male", "female"} and all(r["comparable"] for r in rows)
    assert typical_ranges("vitamin_d", "ng/mL") == []  # not in the table: nothing invented
