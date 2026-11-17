"""Report layouts common on Indian lab reports: urine examination (CUE), asterisk marks, methodology column."""
from ayumitra_ai.nlp.lab_extraction import extract_lab_results, parse_line

CUE = """Test Description  Value(s)  Biological Reference Range  Unit(s)  Methodology
Complete Urine Examination (CUE)- Urine
Volume  20  ml
Colour*  Pale Yellow  Pale Yellow  Visual
Transparency (Appearance)*  Clear  Clear  Visual
Reaction (pH)*  6.5  4.5-8  pH Indicators
Specific Gravity*  1.015  1.003-1.030  Ion concentration
Urine Protein (Albumin)*  Negative  Negative  Tetrabromophenol blue/
Urine Glucose (sugar)*  Positive  Negative  GOD-POD/Benedicts
Urobilinogen*  Normal  Normal  Modified Ehrlich's method
Pus Cells (WBCs)*  2-3  0-5  Microscopy
Epithelial Cells*  6-8  0-4  Microscopy
Red blood Cells*  Absent  Absent  Microscopy
SAMPLE ID  2561174
Collection Time : Dec 14, 2024, 10:02 a.m.""".splitlines()


def _by_name():
    return {r.name_as_printed: r for r in extract_lab_results(CUE)}


def test_urine_examination_rows_extracted_as_printed():
    rows = _by_name()
    assert set(rows) == {"Volume", "Colour", "Transparency (Appearance)", "Reaction (pH)", "Specific Gravity",
                         "Urine Protein (Albumin)", "Urine Glucose (sugar)", "Urobilinogen", "Pus Cells (WBCs)",
                         "Epithelial Cells", "Red blood Cells"}
    assert (rows["Volume"].value_text, rows["Volume"].unit) == ("20", "ml")
    assert (rows["Reaction (pH)"].value_text, rows["Reaction (pH)"].reference_range_text) == ("6.5", "4.5-8")
    assert rows["Specific Gravity"].reference_high == "1.030"
    assert (rows["Colour"].value_text, rows["Colour"].reference_range_text) == ("Pale Yellow", "Pale Yellow")


def test_methodology_column_is_not_part_of_the_result():
    r = _by_name()["Reaction (pH)"]
    assert "Indicators" not in r.reference_range_text and r.unit == ""


def test_word_results_only_within_when_they_match_the_reference():
    rows = _by_name()
    assert rows["Urine Protein (Albumin)"].range_status == "within"
    assert rows["Urine Glucose (sugar)"].range_status == "unknown"  # Positive vs Negative: not guessed


def test_ranged_counts_compared_on_both_ends():
    rows = _by_name()
    assert rows["Pus Cells (WBCs)"].range_status == "within"
    assert rows["Epithelial Cells"].range_status == "above"


def test_urine_microscopy_not_merged_with_blood_counts():
    assert _by_name()["Red blood Cells"].normalized_name != "rbc"
    assert parse_line("RBC Count  4.8  mill/cumm  4.5-5.5").normalized_name == "rbc"


def test_a_lone_reference_range_is_never_a_result():
    assert parse_line("Hemoglobin  13.0-17.0  g/dL") is None


def test_trailing_words_need_a_reference_or_unit_to_count():
    assert parse_line("Patient seen 2 times in clinic") is None
    assert parse_line("Glucose  92  mg/dL  70-110  Hexokinase method").value_text == "92"


def test_name_glued_to_value_still_parsed_with_range_after_it():
    r = parse_line("SGPT (ALT)72 H  U/L  7-56")
    assert (r.normalized_name, r.value_text, r.reference_range_text) == ("alt", "72", "7-56")


def test_scanned_asterisk_variants_and_hpf_unit():
    r = parse_line("Specinc Gravity.  1.020  1.003-1.030  on conceMrabon")
    assert (r.name_as_printed, r.value_text, r.reference_range_text) == ("Specinc Gravity", "1.020", "1.003-1.030")
    r = parse_line("Pus Cells (WBCs)*  2-3  0-5  /hpf  Microscopy")
    assert (r.value_text, r.reference_range_text, r.unit, r.range_status) == ("2-3", "0-5", "/hpf", "within")
    assert parse_line("Crystals\"  Absent  Absent  Microscopy").name_as_printed == "Crystals"
    assert parse_line("S. Creatinine  0.9  mg/dL  0.7-1.3").normalized_name == "creatinine"


def test_impossible_range_is_never_used_for_a_verdict():
    r = parse_line("Reaction (pH)*  6.0  45-8  pH Indicators:")
    assert r.value_text == "6.0" and r.range_status == "unknown" and r.reference_low is None
    assert r.needs_review and any("could not be read" in i for i in r.issues)


def test_word_style_ranges_and_flag_column():
    r = parse_line("HDL Cholesterol  46  mg/dL  Above 40  Normal")
    assert (r.value_text, r.reference_range_text, r.reference_low, r.reference_high, r.range_status) == \
        ("46", "Above 40", "40", None, "within")
    r = parse_line("Fasting Blood Glucose  108  mg/dL  70 – 99  High*")
    assert (r.normalized_name, r.lab_flag, r.range_status) == ("glucose_fasting", "high", "above")
    r = parse_line("LDL Cholesterol (calculated)  118  mg/dL  Below 100  Near optimal*")
    assert (r.reference_high, r.range_status) == ("100", "above")
    assert parse_line("Total WBC Count  7.4  10³/µL  4.0 – 11.0  Normal").unit_canonical == "10^3/µL"


def test_page_furniture_is_not_a_result():
    assert parse_line("Page 1") is None and parse_line("Below 5.7") is None
    assert parse_line("Glucose  92").value_text == "92"


def test_pdf_cells_rebuilt_into_rows():
    from ayumitra_ai.documents.extract import visual_rows
    cells = [("Haemoglobin", 50, 300), ("13.8", 250, 300), ("g/dL", 330, 300), ("13.0 – 17.0", 440, 300),
             ("Normal", 590, 300), ("MCV", 50, 330), ("85.5", 250, 330), ("fL", 330, 330), ("80 – 100", 440, 330)]
    lines = [{"text": t, "bbox": [x, y, x + 40, y + 10]} for t, x, y in cells]
    rows = visual_rows(lines)
    assert rows == ["Haemoglobin  13.8  g/dL  13.0 – 17.0  Normal", "MCV  85.5  fL  80 – 100"]
    assert [parse_line(r).value_text for r in rows] == ["13.8", "85.5"]
