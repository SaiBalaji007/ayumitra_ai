import json
import random
from decimal import Decimal

import pytest

from ayumitra_ai.nlp.lab_extraction import compare, extract_lab_results, normalize_test_name, parse_line, parse_range
from ayumitra_ai.nlp.medicines import RxNormLexicon
from ayumitra_ai.nlp.prescriptions import extract_prescription, parse_item, read_frequency
from ayumitra_ai.nlp.units import exact_convert, normalize_unit
from evaluation.synthetic_docs import make_lab_report, make_prescription


@pytest.fixture
def lexicon(tmp_path):
    d = tmp_path / "rxnorm"
    d.mkdir()
    ing = [{"rxcui": "6809", "name": "metformin"}, {"rxcui": "17767", "name": "amlodipine"},
           {"rxcui": "161", "name": "acetaminophen"}, {"rxcui": "6750", "name": "merbromin"}]
    (d / "in.json").write_text(json.dumps({"concepts": ing}))
    (d / "bn.json").write_text(json.dumps({"concepts": [{"rxcui": "153165", "name": "Lipitor"}]}))
    lex = RxNormLexicon(d, online=False)
    with lex._cache() as conn:  # pre-seed the brand cache so no network is needed
        conn.execute("INSERT INTO brand_in VALUES ('153165', '[\"atorvastatin\"]')")
    return lex


class TestUnits:
    def test_spelling_variants_unified(self):
        assert normalize_unit("gm/dl").canonical == "g/dL"
        assert normalize_unit("mg/dl").canonical == "mg/dL"
        assert normalize_unit("cells/cumm").canonical == "cells/µL"
        assert normalize_unit("furlongs").known is False

    def test_only_exact_conversions(self):
        assert exact_convert(Decimal("1.5"), "lakh/µL") == (Decimal("150000.0"), "/µL")
        assert exact_convert(Decimal("90"), "mg/dL") is None  # mass<->molar needs the analyte: never converted


class TestLabExtraction:
    def test_parses_value_unit_range_and_lab_flag(self):
        r = parse_line("Haemoglobin    10.2 L    g/dL    12.0 - 15.5")
        assert (r.normalized_name, r.value_text, r.unit, r.unit_canonical) == ("hemoglobin", "10.2", "g/dL", "g/dL")
        assert (r.reference_low, r.reference_high, r.reference_range_text) == ("12.0", "15.5", "12.0 - 15.5")
        assert r.lab_flag == "low" and r.range_status == "below" and not r.needs_review

    def test_lab_flag_kept_separate_from_own_comparison(self):
        r = parse_line("Serum Creatinine  1.30  mg/dL  0.6 - 1.2")  # lab printed no flag
        assert r.lab_flag == "" and r.range_status == "above"

    def test_upper_bound_only_ranges(self):
        r = parse_line("Total Cholesterol    212 H    mg/dL    < 200")
        assert r.reference_low is None and r.reference_high == "200" and r.range_status == "above"
        assert parse_range("Up to 40") == (None, Decimal("40"))
        assert parse_range("> 40") == (Decimal("40"), None)

    def test_missing_fields_stay_empty_and_lower_confidence(self):
        r = parse_line("Glucose  92")
        assert r.unit == "" and r.reference_range_text == "" and r.range_status == "unknown"
        assert "no unit printed" in r.issues and r.confidence < 1.0

    def test_ocr_confidence_drives_review(self):
        assert parse_line("Haemoglobin 13.1 g/dL 12.0 - 15.5", ocr_confidence=0.6).needs_review

    def test_qualitative_values(self):
        r = parse_line("HBsAg  Negative")
        assert r.value_text.lower() == "negative" and r.value_numeric is None

    def test_header_and_prose_lines_ignored(self):
        lines = ["SUNRISE DIAGNOSTICS", "Test Name    Result    Units    Biological Reference Interval",
                 "Reference ranges are those of this laboratory."]
        assert extract_lab_results(lines) == []

    def test_synthetic_report_all_rows_exact(self):
        doc = make_lab_report(random.Random(3), "x")
        results = extract_lab_results(doc.text.splitlines())
        got = {(r.name_as_printed, r.value_text, r.unit, r.reference_range_text) for r in results}
        want = {(row.name, row.value, row.unit, row.reference_range) for row in doc.lab_rows}
        assert got == want
        flags = {r.name_as_printed: r.lab_flag for r in results}
        for row in doc.lab_rows:
            assert flags[row.name] == {"H": "high", "L": "low", "": ""}[row.flag]

    def test_name_normalisation(self):
        assert normalize_test_name("SGPT (ALT)") == ("alt", 1.0)
        assert normalize_test_name("Glycated Haemoglobin")[0] == "hba1c"
        assert normalize_test_name("Some New Test")[1] < 1.0

    def test_compare(self):
        assert compare(Decimal(5), Decimal(1), Decimal(10)) == "within"
        assert compare(None, Decimal(1), Decimal(2)) == "unknown"


class TestMedicines:
    def test_exact_ingredient_and_brand(self, lexicon):
        m = lexicon.match("Metformin")
        assert m.status == "exact_ingredient" and m.generic_name == "metformin" and not m.needs_review
        b = lexicon.match("LIPITOR")
        assert b.status == "exact_brand" and b.generic_name == "atorvastatin"

    def test_typo_is_a_suggestion_never_an_answer(self, lexicon):
        m = lexicon.match("Metfromin")
        assert m.status == "suggestion" and m.generic_name == "" and m.needs_review
        assert m.suggestions[0]["name"] == "metformin"  # closest, but only suggested

    def test_unknown_is_unrecognized(self, lexicon):
        m = lexicon.match("Dolozzz")
        assert m.status == "unrecognized" and m.generic_name == "" and m.needs_review


class TestPrescriptions:
    def test_line_fields_as_written(self, lexicon):
        it = parse_item("1. Tab. Metformin 500 mg  1-0-1  after food  x 30 days", 1, lexicon)
        assert (it.dosage_form, it.name_as_written, it.strength) == ("tablet", "Metformin", "500 mg")
        assert (it.frequency, it.timing, it.duration) == ("1-0-1", "after food", "30 days")
        assert it.frequency_reading == "1 in the morning, 1 in the night"
        assert it.fields_needing_review == [] and it.medicine["generic_name"] == "metformin"

    def test_missing_fields_are_never_filled(self, lexicon):
        it = parse_item("Tab. Amlodipine 5 mg", 1, lexicon)
        assert it.frequency == "" and it.duration == "" and it.timing == ""
        assert {"frequency", "duration"} <= set(it.fields_needing_review)

    def test_uncertain_name_needs_review(self, lexicon):
        it = parse_item("Tab. Metfromin 500 mg BD", 1, lexicon)
        assert "name" in it.fields_needing_review and it.medicine["status"] == "suggestion"
        assert it.frequency_reading == "twice a day"

    def test_low_ocr_confidence_flags_everything(self, lexicon):
        it = parse_item("Tab. Metformin 500 mg BD x 5 days", 1, lexicon, ocr_confidence=0.5)
        assert {"name", "strength", "frequency", "duration"} <= set(it.fields_needing_review)

    def test_frequency_readings(self):
        assert read_frequency("TDS") == "three times a day"
        assert read_frequency("0-0-1") == "1 in the night"
        assert read_frequency("weird") == ""

    def test_synthetic_prescription(self, lexicon):
        doc = make_prescription(random.Random(5), "x")
        items = extract_prescription(doc.text.splitlines(), lexicon)
        assert len(items) == len(doc.medicines)
        for it, med in zip(items, doc.medicines, strict=True):
            assert it.name_as_written == med.name and it.strength == med.strength
            assert it.frequency == med.frequency and it.duration == med.duration and it.timing == med.timing


def test_inn_names_map_to_rxnorm(lexicon):
    m = lexicon.match("Paracetamol")
    assert m.status == "exact_ingredient" and m.generic_name == "acetaminophen" and "INN" in m.matched_name


class TestOcrRobustRows:
    def test_names_ending_in_digits(self):
        from ayumitra_ai.nlp.lab_extraction import parse_line

        for line, norm in (("T3  1.2  ng/mL  0.8 - 2.0", "t3"), ("Vitamin B12  450  pg/mL  200 - 900", "vitamin_b12")):
            r = parse_line(line)
            assert r is not None and r.normalized_name == norm and r.reference_range_text

    def test_ocr_misread_name_is_recognised_but_flagged(self):
        from ayumitra_ai.nlp.lab_extraction import parse_line

        r = parse_line("HbAlc3.6 L  % 4.0 - 5.6")
        assert r.name_as_printed == "HbAlc"          # kept exactly as scanned
        assert r.normalized_name == "hba1c"
        assert (r.value_text, r.unit, r.reference_range_text, r.lab_flag) == ("3.6", "%", "4.0 - 5.6", "low")
        assert r.needs_review and any("misread" in i for i in r.issues)

    def test_unknown_glued_text_is_not_split(self):
        from ayumitra_ai.nlp.lab_extraction import parse_line

        assert parse_line("Lab No: SD37554 Sample: Blood") is None
        assert parse_line("Zentrine12 units") is None  # unknown name: never guessed


class TestRealReportLayouts:
    """From a real-world lab report layout (values changed): status column, mg/L unit, header noise."""

    def test_status_column_and_mg_per_litre(self):
        from ayumitra_ai.nlp.lab_extraction import parse_line

        r = parse_line("VITAMIN E(TOCOPHEROL)  10.00  Noma  5.00-18.00  mg/L")
        assert (r.value_text, r.unit, r.reference_range_text, r.range_status) == ("10.00", "mg/L", "5.00-18.00", "within")
        assert r.needs_review  # name not in the alias list

    def test_header_ids_and_barcodes_are_not_results(self):
        from ayumitra_ai.nlp.lab_extraction import extract_lab_results

        lines = ["DRLOGYPATHOLOGYLAB  01234567890912345678", "wwwidrlogy.com Sample Collection 0123456789",
                 "UHID:556 Ref. By:Dr.Hiren Shah", "Lab No 004512"]
        assert extract_lab_results(lines) == []


class TestScannedUnitColumn:
    def test_unreadable_unit_keeps_value_and_range_and_flags(self):
        from ayumitra_ai.nlp.lab_extraction import parse_line

        r = parse_line("Fasting Blood Sugar  62 L  7p/8w  70 - 100")
        assert (r.value_text, r.unit, r.reference_range_text, r.lab_flag) == ("62", "7p/8w", "70 - 100", "low")
        assert r.needs_review

    def test_range_is_never_reported_as_the_value(self):
        from ayumitra_ai.nlp.lab_extraction import parse_line

        assert parse_line("Total Cholesterol  7p/8w  < 200") is None
        assert parse_line("Triglycerides 26 7p/3w < 150").value_text == "26"
