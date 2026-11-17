"""Typical ranges: used only when the report printed none, sex-aware, unit-checked, and labelled as typical."""
from decimal import Decimal
from unittest import mock

from rest_framework.test import APITestCase

from documents.analysis import _store
from documents.models import MedicalDocument
from medical_reports.models import ExtractedReport
from medical_reports.tests import make_user
from patients.models import PatientProfile

NHLBI = {"publisher": "National Heart, Lung, and Blood Institute (NHLBI), NIH", "source_title": "Anemia: Diagnosis",
         "url": "https://www.nhlbi.nih.gov/health/anemia/diagnosis", "source_id": "nhlbi-anemia-diagnosis"}
HB = [{**NHLBI, "sex": "male", "low": "14", "high": "17", "unit": "g/dL", "display": "14 to 17 g/dL (adult men)",
       "comparable": True, "quote": "Adult men: 14 to 17 gm/dL", "low_inclusive": True, "high_inclusive": True},
      {**NHLBI, "sex": "female", "low": "12", "high": "15", "unit": "g/dL", "display": "12 to 15 g/dL (adult women)",
       "comparable": True, "quote": "Adult women: 12 to 15 gm/dL", "low_inclusive": True, "high_inclusive": True}]
TG = [{"sex": "any", "low": None, "high": "150", "high_inclusive": False, "low_inclusive": True, "unit": "mg/dL",
       "display": "less than 150 mg/dL (adults)", "comparable": True, "quote": "Healthy less than 150mg/dL",
       "publisher": "MedlinePlus", "source_title": "Triglycerides Test", "url": "https://medlineplus.gov/x",
       "source_id": "mlp-lab-triglycerides-test"}]


def row(name, norm, value, unit, ref="", typical=None):
    d = {"name_as_printed": name, "normalized_name": norm, "value_text": value, "value_numeric": value, "unit": unit,
         "reference_range_text": ref, "reference_low": None, "reference_high": None, "lab_flag": "", "confidence": 0.9,
         "page": 1}
    if ref:
        lo, hi = ref.split("-")
        d.update(reference_low=lo, reference_high=hi)
    if typical is not None:
        d["typical_ranges"] = typical
    return d


class TypicalRangeTests(APITestCase):
    def setUp(self):
        self.user = make_user("t@example.com")
        self.client.force_authenticate(self.user)
        self.doc = MedicalDocument.objects.create(owner=self.user, file="documents/x.pdf", original_filename="r.pdf",
                                                  content_type="application/pdf", file_size=1, sha256="0" * 64,
                                                  document_type="lab_report")
        result = {"extraction": {"pages": []}, "classification": {"document_type": "lab_report", "confidence": 1.0},
                  "lab_results": [row("Haemoglobin", "hemoglobin", "13.2", "g/dL", typical=HB),
                                  row("Triglycerides", "triglycerides", "150", "mg/dL", typical=TG),
                                  row("Triglycerides (mg/L)", "triglycerides", "1.2", "mg/L",
                                      typical=[{**TG[0], "comparable": False}]),
                                  row("Glucose", "glucose_fasting", "92", "mg/dL", ref="70-110",
                                      typical=None)]}
        with mock.patch("documents.analysis.DocumentPage"):
            _store(self.doc, result)
        self.report = ExtractedReport.objects.get(document=self.doc)

    def params(self):
        body = self.client.get(f"/api/reports/{self.report.pk}/").json()
        return {p["name_as_printed"]: p for p in body["parameters"]}, body

    def test_sex_unknown_shows_both_options_and_compares_nothing(self):
        p = self.params()[0]["Haemoglobin"]
        self.assertEqual((p["range_source"], p["range_status"]), ("typical", "unknown"))
        self.assertIsNone(p["typical_range"]["selected"])
        self.assertEqual({o["sex"] for o in p["typical_range"]["options"]}, {"male", "female"})

    def test_profile_sex_selects_the_range(self):
        PatientProfile.objects.update_or_create(user=self.user, defaults={"sex": "male"})
        p = self.params()[0]["Haemoglobin"]
        self.assertEqual((p["range_status"], p["typical_range"]["selected"]["sex"]), ("below", "male"))  # 13.2 < 14
        PatientProfile.objects.filter(user=self.user).update(sex="female")
        self.assertEqual(self.params()[0]["Haemoglobin"]["range_status"], "within")  # 12-15

    def test_less_than_bound_is_exclusive(self):
        self.assertEqual(self.params()[0]["Triglycerides"]["range_status"], "above")  # 150 is not "less than 150"

    def test_different_unit_is_never_compared(self):
        p = self.params()[0]["Triglycerides (mg/L)"]
        self.assertEqual((p["range_source"], p["range_status"]), ("typical", "unknown"))

    def test_the_labs_printed_range_always_wins(self):
        p = self.params()[0]["Glucose"]
        self.assertEqual((p["range_source"], p["range_status"], p["typical_range"]), ("lab", "within", None))

    def test_typical_above_counts_as_abnormal(self):
        self.assertEqual(self.params()[1]["abnormal_count"], 1)  # triglycerides 150 vs < 150
