import random

import pytest

from ayumitra_ai.documents.classify import classify
from ayumitra_ai.documents.extract import extract_document, extract_pdf
from ayumitra_ai.documents.ocr import OcrLine, group_rows, sort_reading_order
from evaluation.synthetic_docs import make_lab_report, make_prescription, render_pdf


@pytest.fixture
def rng():
    return random.Random(7)


class TestClassification:
    def test_lab_report(self, rng):
        c = classify(make_lab_report(rng, "x").text)
        assert c.document_type == "lab_report" and c.confidence > 0.5
        assert "lab_report" in c.cues

    def test_prescription(self, rng):
        c = classify(make_prescription(rng, "x").text)
        assert c.document_type == "prescription" and c.confidence > 0.5

    def test_discharge_summary(self):
        text = "DISCHARGE SUMMARY\nDate of admission: 01/10\nCourse in hospital: stable.\nDischarge advice: rest."
        assert classify(text).document_type == "discharge_summary"

    def test_unrelated_text_is_other(self):
        c = classify("Dear customer, your electricity bill for October is attached.")
        assert c.document_type == "other" and c.confidence == 0.0


class TestPdfExtraction:
    def test_digital_pdf_uses_text_layer_exactly(self, rng):
        doc = make_lab_report(rng, "x")
        res = extract_pdf(render_pdf(doc))
        assert len(res.pages) == 1
        page = res.pages[0]
        assert page.method == "text_layer" and page.confidence is None
        for row in doc.lab_rows:
            assert row.name in page.text and row.value in page.text and row.reference_range in page.text

    def test_pdf_tables_detected(self):
        import fitz

        pdf = fitz.open()
        page = pdf.new_page()
        cells = [["Test", "Result", "Unit"], ["Glucose", "92", "mg/dL"], ["Urea", "30", "mg/dL"]]
        for r, row in enumerate(cells):
            for c, val in enumerate(row):
                rect = fitz.Rect(50 + c * 120, 50 + r * 25, 170 + c * 120, 75 + r * 25)
                page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                page.insert_textbox(rect, val, fontsize=10, align=1)
        page.insert_text((50, 200), "Additional lines of report text so the page has a text layer.", fontsize=10)
        res = extract_pdf(pdf.tobytes())
        tables = res.pages[0].tables
        assert tables and ["Glucose", "92", "mg/dL"] in tables[0].rows

    def test_unsupported_type(self):
        with pytest.raises(ValueError):
            extract_document(b"x", "text/plain")


def test_reading_order_and_rows():
    lines = [OcrLine("92", 0.9, (300, 102, 340, 120)), OcrLine("Glucose", 0.9, (50, 100, 150, 120)),
             OcrLine("Header", 0.9, (50, 40, 200, 60)), OcrLine("mg/dL", 0.9, (400, 99, 460, 119))]
    ordered = sort_reading_order(lines)
    assert [ln.text for ln in ordered] == ["Header", "Glucose", "92", "mg/dL"]
    rows = group_rows(ordered)
    assert [[ln.text for ln in r] for r in rows] == [["Header"], ["Glucose", "92", "mg/dL"]]


def test_report_pdf_export_contains_printed_values_and_disclaimer():
    import fitz

    from ayumitra_ai.export import render_report_pdf

    data = {"title": "Fictional CBC", "report_date": "2026-11-01",
            "parameters": [{"name_as_printed": "Haemoglobin", "value_text": "10.2", "unit": "g/dL",
                            "reference_range_text": "12.0 - 15.5", "lab_flag": "low", "range_status": "below"}] * 40,
            "explanations": [{"parameter": "Haemoglobin", "answer": {"status": "answered", "answer": "Claim text. [1]",
                              "citations": [{"id": "1", "title": "Hemoglobin Test", "section": "Results", "url": "https://medlineplus.gov/x"}]}}]}
    pdf = fitz.open(stream=render_report_pdf(data), filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    assert pdf.page_count >= 2  # 40 rows flow onto a second page
    assert "10.2" in text and "12.0 - 15.5" in text and "Below lab range" in text
    assert "Hemoglobin Test" in text and "not a diagnosis" in text
