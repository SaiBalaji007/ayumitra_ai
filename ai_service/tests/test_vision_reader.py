"""Vision prescription reader: output parsing, line building, cross-checking and fallbacks (no model needed)."""
from types import SimpleNamespace

from ayumitra_ai import api
from ayumitra_ai.documents import vlm


def test_parses_model_json_and_drops_empty_rows():
    out = vlm._parse('Sure! {"medicines": [{"number": 1, "form": "Tab", "name": "Shelcal", "strength": "500", '
                     '"dose": "1", "frequency": "1 x 2", "timing": "", "duration": "1 month"}, {"name": ""},]}')
    assert len(out) == 1 and out[0]["name"] == "Shelcal" and out[0]["duration"] == "1 month"
    assert vlm._parse("no json here") == []


def test_line_is_built_in_parser_order():
    row = {"form": "Tab", "name": "D3 Must", "strength": "60K", "dose": "1 tab", "frequency": "once weekly",
           "timing": "", "duration": "4 weeks"}
    assert vlm.as_line(row) == "Tab D3 Must 60K 1 tab once weekly x 4 weeks"


def test_support_tolerates_handwriting_misreads():
    page = "helcal Soo  Dgmst 60k  NeuroknLe 1tbonee"
    assert vlm.support_in_text("Shelcal", page) > 0.8
    assert vlm.support_in_text("Paracetamol", page) < 0.6


def _ex(conf):
    return SimpleNamespace(pages=[SimpleNamespace(method="ocr_paddle", confidence=conf)], text="helcal Soo", warnings=[])


def test_vision_rows_are_normalised_and_flagged(monkeypatch):
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "read_prescription", lambda d, c: [
        {"form": "Tab", "name": "Shelcal", "strength": "500", "dose": "1", "frequency": "1 x 2", "timing": "",
         "duration": "1 month"},
        {"form": "Tab", "name": "Zentrovax", "strength": "", "dose": "", "frequency": "", "timing": "", "duration": ""}])
    items = api.read_prescription_with_vision(b"x", "image/png", _ex(0.7), [])
    shelcal, unknown = items
    assert shelcal["read_by"] == "vision" and shelcal["medicine"]["status"] == "indian_brand"
    assert (shelcal["strength"], shelcal["frequency"], shelcal["duration"]) == ("500", "1 x 2", "1 month")
    assert "name" not in shelcal["fields_needing_review"]
    # nothing written -> nothing filled in, everything flagged; unknown name not backed by the page -> flagged
    assert unknown["frequency"] == "" and {"name", "frequency", "duration"} <= set(unknown["fields_needing_review"])


def test_clean_printed_or_digital_documents_skip_the_vision_model(monkeypatch):
    monkeypatch.setattr(vlm, "available", lambda: True)
    called = []
    monkeypatch.setattr(vlm, "read_prescription", lambda d, c: called.append(1) or [])
    good = [{"frequency": "BD", "fields_needing_review": []}]
    assert api.read_prescription_with_vision(b"x", "image/png", _ex(0.95), good) is None
    digital = SimpleNamespace(pages=[SimpleNamespace(method="text_layer", confidence=None)], text="", warnings=[])
    assert api.read_prescription_with_vision(b"x", "application/pdf", digital, []) is None
    assert called == []


def test_model_failure_keeps_the_ocr_result(monkeypatch):
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "read_prescription", lambda d, c: None)
    assert api.read_prescription_with_vision(b"x", "image/png", _ex(0.5), []) is None


def test_short_values_are_never_treated_as_confirmed_by_the_page():
    assert vlm.support_in_text("1", "Tab 1 x 1 daily") == 0.0
    assert vlm.support_in_text("17", "17 days 17") == 0.0


def test_model_fields_are_used_as_read_not_reparsed(monkeypatch):
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "read_prescription", lambda d, c: [
        {"form": "Cap", "name": "Nexpro", "strength": "150", "dose": "1 x 1", "frequency": "1 cap once morning",
         "timing": "empty stomach", "duration": "7 days"},
        {"form": "", "name": "D3 Must", "strength": "60K", "dose": "", "frequency": "once", "timing": "oral",
         "duration": "4 weeks"}])
    nexpro, d3 = api.read_prescription_with_vision(b"x", "image/png", _ex(0.7), [])
    assert (nexpro["frequency"], nexpro["frequency_reading"]) == ("1 cap once morning", "once a day, in the morning")
    assert (nexpro["dosage_form"], nexpro["timing"], nexpro["duration"]) == ("capsule", "empty stomach", "7 days")
    # a bare "once" has no safe reading (once a day? once a week?) -> no reading, flagged for the user
    assert d3["frequency_reading"] == "" and "frequency" in d3["fields_needing_review"]
    assert d3["timing"] == ""  # "oral" is a route, not a timing


# --- NER second opinion -----------------------------------------------------------------------------------
from ayumitra_ai.nlp import ner as ner_mod  # noqa: E402


class _FakeNER:
    def __init__(self, ents):
        self.ents = ents

    def extract(self, text, min_confidence=0.5):
        out = []
        for word, cat in self.ents:
            i = text.find(word)
            out.append(ner_mod.Entity(word, cat, cat, i, i + len(word), 0.95))
        return ner_mod._merge_fragments(out, text)


def test_ner_fragments_are_joined_into_the_written_word():
    text = "Tab Amlodipine 5 mg OD"
    ents = [ner_mod.Entity("Am", "Medication", "medication", 4, 6, 1.0),
            ner_mod.Entity("lo", "Medication", "medication", 6, 8, 0.93),
            ner_mod.Entity("dipine", "Medication", "medication", 8, 14, 0.86)]
    (e,) = ner_mod._merge_fragments(ents, text)
    assert (e.text, e.confidence) == ("Amlodipine", 0.86)


def test_ner_warns_only_about_medicines_missing_from_the_list():
    text = "Tab Metformin 500 mg BD\nTab Amlodipine 5 mg OD\nweakness"
    fake = _FakeNER([("Metformin", "medication"), ("Amlodipine", "medication"), ("weakness", "symptom")])
    assert ner_mod.possibly_missed_medicines(text, ["Metformin"], ner=fake) == ["Amlodipine"]
    assert ner_mod.possibly_missed_medicines(text, ["Metformin", "Amlodipin"], ner=fake) == []  # close spelling = listed


def test_ner_skips_garbled_handwriting_pages(monkeypatch):
    monkeypatch.setattr(ner_mod, "available", lambda: True)
    monkeypatch.setattr(ner_mod, "possibly_missed_medicines", lambda *a, **k: ["Nexpro"])
    assert api.missed_medicine_warnings(_ex(0.6), []) == []  # OCR confidence too low: no second opinion
    good = SimpleNamespace(pages=[SimpleNamespace(method="text_layer", confidence=None, text="Tab Nexpro 40")], text="")
    (w,) = api.missed_medicine_warnings(good, [])
    assert "Nexpro" in w and "not in the list" in w
