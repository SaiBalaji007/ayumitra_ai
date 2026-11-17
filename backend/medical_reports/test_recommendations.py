from datetime import date
from decimal import Decimal

from rest_framework.test import APITestCase

from medical_reports.models import ExtractedReport, LabParameter
from medical_reports.tests import make_user
from documents.models import MedicalDocument
from patients.models import PatientProfile

_n = 0


def report(owner, day, rows):
    """rows: (normalized_name, printed name, value, low, high, lab_flag)"""
    global _n
    _n += 1
    doc = MedicalDocument.objects.create(owner=owner, file=f"documents/{owner.pk}/{_n}.pdf", original_filename="r.pdf",
                                         content_type="application/pdf", file_size=1, sha256=f"{_n:064d}",
                                         document_type="lab_report")
    rep = ExtractedReport.objects.create(document=doc, report_date=day)
    for norm, name, value, low, high, flag in rows:
        LabParameter.objects.create(report=rep, normalized_name=norm, name_as_printed=name, value_text=str(value),
                                    value_numeric=Decimal(str(value)), unit="u", reference_range_text=f"{low}-{high}",
                                    reference_low=Decimal(str(low)), reference_high=Decimal(str(high)), lab_flag=flag)
    return rep


def ids(items):
    return [i["id"] for i in items]


def foods(item):
    return " | ".join(f["name"] for f in item["include"])


class RecommendationTests(APITestCase):
    def setUp(self):
        self.alice, self.bob = make_user("alice@example.com"), make_user("bob@example.com")
        self.client.force_authenticate(self.alice)

    def get(self):
        res = self.client.get("/api/recommendations/")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/recommendations/").status_code, 401)

    def test_no_reports_gives_baseline_only_and_reports_missing_profile(self):
        body = self.get()
        self.assertEqual(body["generated_from"]["reports_used"], 0)
        self.assertEqual(ids(body["diet"]["items"]), ["balanced_plate"])
        self.assertTrue(body["diet"]["meal_plan"]["available"])
        self.assertEqual(ids(body["lifestyle"]["items"]), ["activity", "sleep", "hydration", "stress", "habits"])
        self.assertIn("date_of_birth", body["generated_from"]["missing_profile_fields"])
        self.assertIn("not medical advice", body["disclaimer"])
        self.assertIn("14416", " ".join(body["lifestyle"]["items"][3]["tips"]))

    def test_results_trigger_rules_with_reason_and_sources(self):
        report(self.alice, date(2026, 5, 1), [("ldl", "LDL Cholesterol", 172, 0, 100, "high"),
                                              ("hemoglobin", "Haemoglobin", 10.1, 12, 15, "low"),
                                              ("tsh", "TSH", 2.1, 0.4, 4.0, "")])
        body = self.get()
        got = ids(body["diet"]["items"])
        self.assertIn("heart_healthy_fats", got)
        self.assertIn("iron_rich", got)
        self.assertNotIn("thyroid", got)  # TSH within the lab's range
        iron = next(i for i in body["diet"]["items"] if i["id"] == "iron_rich")
        self.assertIn("Haemoglobin 10.1", iron["why"])
        self.assertIn("12-15", iron["why"])
        self.assertTrue(iron["needs_doctor"])
        self.assertIn("Don't start iron tablets", iron["doctor_note"])
        self.assertTrue(all(s["url"].startswith("https://") for i in body["diet"]["items"] for s in i["sources"]))
        self.assertEqual({f["parameter"] for f in body["findings"]}, {"ldl", "hemoglobin"})

    def test_latest_report_wins(self):
        report(self.alice, date(2025, 1, 1), [("vitamin_d", "Vitamin D", 12, 30, 100, "low")])
        report(self.alice, date(2026, 1, 1), [("vitamin_d", "Vitamin D", 45, 30, 100, "")])
        self.assertNotIn("vitamin_d", ids(self.get()["diet"]["items"]))

    def test_kidney_results_give_no_food_list_and_no_meal_plan(self):
        report(self.alice, date(2026, 5, 1), [("creatinine", "Serum Creatinine", 2.4, 0.6, 1.2, "high")])
        body = self.get()
        kidney = next(i for i in body["diet"]["items"] if i["id"] == "kidney_individual")
        self.assertEqual(kidney["include"], [])
        self.assertTrue(kidney["needs_doctor"])
        self.assertFalse(body["diet"]["meal_plan"]["available"])
        hydration = next(i for i in body["lifestyle"]["items"] if i["id"] == "hydration")
        self.assertTrue(hydration["needs_doctor"])
        self.assertIn("fluid limit", hydration["doctor_note"])

    def test_critical_flag_raises_alert_and_activity_needs_doctor(self):
        report(self.alice, date(2026, 5, 1), [("glucose_fasting", "Fasting Blood Sugar", 320, 70, 100, "critical_high")])
        body = self.get()
        self.assertEqual(len(body["alerts"]), 1)
        self.assertIn("critical", body["alerts"][0])
        sugar = next(i for i in body["diet"]["items"] if i["id"] == "blood_sugar")
        self.assertTrue(sugar["needs_doctor"])
        activity = next(i for i in body["lifestyle"]["items"] if i["id"] == "activity")
        self.assertTrue(activity["needs_doctor"])

    def test_allergies_and_vegetarian_preference_remove_foods(self):
        PatientProfile.objects.update_or_create(user=self.alice, defaults={
            "allergies": "Peanuts, milk", "dietary_preference": "Vegetarian"})
        report(self.alice, date(2026, 5, 1), [("ldl", "LDL", 172, 0, 100, "high"), ("hemoglobin", "Hb", 10, 12, 15, "low")])
        body = self.get()
        chol = next(i for i in body["diet"]["items"] if i["id"] == "heart_healthy_fats")
        iron = next(i for i in body["diet"]["items"] if i["id"] == "iron_rich")
        self.assertNotIn("Fish", foods(chol))
        self.assertNotIn("groundnut", foods(chol))
        self.assertNotIn("Eggs", foods(iron))
        self.assertIn("Green leafy", foods(iron))
        self.assertTrue(iron["removed_for_you"])
        plan = " ".join(f["name"] for slot in body["diet"]["meal_plan"]["slots"].values() for f in slot)
        for word in ("peanut", "milk", "egg", "fish", "chicken", "Buttermilk", "paneer", "curd"):
            self.assertNotIn(word.lower(), plan.lower())
        self.assertEqual(body["generated_from"]["allergy_groups_excluded"], ["dairy", "peanut"])

    def test_bmi_from_profile(self):
        PatientProfile.objects.update_or_create(user=self.alice, defaults={"height_cm": Decimal("170"), "weight_kg": Decimal("72.0")})
        habits = next(i for i in self.get()["lifestyle"]["items"] if i["id"] == "habits")
        self.assertIn("BMI from your profile is 24.9", habits["summary"])

    def test_other_users_results_are_not_used(self):
        report(self.bob, date(2026, 5, 1), [("uric_acid", "Uric Acid", 9.5, 3.5, 7.2, "high")])
        body = self.get()
        self.assertNotIn("uric_acid", ids(body["diet"]["items"]))
        self.assertEqual(body["generated_from"]["reports_used"], 0)

    def test_never_mentions_doses(self):
        report(self.alice, date(2026, 5, 1), [("vitamin_d", "Vitamin D", 9, 30, 100, "low"),
                                              ("vitamin_b12", "B12", 120, 200, 900, "low"),
                                              ("ferritin", "Ferritin", 5, 15, 150, "low")])
        body = self.get()
        body.pop("disclaimer")  # says the content does *not* cure anything
        text = str(body).lower()
        for banned in (" mg", " iu", "mcg", "units a day", "cure"):
            self.assertNotIn(banned, text)


class ParamRangeStatusTests(__import__("django").test.SimpleTestCase):
    """Status for every way a lab prints a result (numbers, ranged counts, words)."""

    def status(self, value_text, ref_text, numeric=None):
        from types import SimpleNamespace
        from medical_reports.logic import param_range_status, parse_range, to_decimal
        lo, hi = parse_range(ref_text)
        if lo is not None and hi is not None and lo > hi:
            lo = hi = None
        return param_range_status(SimpleNamespace(value_text=value_text, reference_range_text=ref_text,
                                                  value_numeric=to_decimal(numeric), reference_low=lo, reference_high=hi))

    def test_numbers(self):
        self.assertEqual(self.status("6.0", "4.5-8", "6.0"), "within")
        self.assertEqual(self.status("9.1", "4.5-8", "9.1"), "above")

    def test_ranged_counts_compare_both_ends(self):
        self.assertEqual(self.status("2-3", "0-5"), "within")
        self.assertEqual(self.status("3-6", "0-5"), "above")

    def test_word_results_neutral_match_or_differ(self):
        self.assertEqual(self.status("Negative", "Negative"), "matches")
        self.assertEqual(self.status("Pale  Yellow", "pale yellow"), "matches")
        self.assertEqual(self.status("Positive", "Negative"), "differs")

    def test_nothing_to_compare(self):
        self.assertEqual(self.status("Absent", ""), "unknown")
        self.assertEqual(self.status("6.0", "45-8", "6.0"), "unknown")  # unreadable range: never a verdict
