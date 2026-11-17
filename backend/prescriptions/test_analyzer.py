from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from rest_framework.test import APITestCase

from medical_reports.tests import make_doc, make_user
from patients.models import PatientProfile
from prescriptions.logic import build_schedule, identified_names, safety_warnings, schedule_for
from prescriptions.models import Prescription, PrescriptionMedicine


def med(**kw):
    base = dict(line_number=1, name_as_written="Metformin", generic_name="", strength="500 mg", dose="1 tab", frequency="",
                timing="", food_instructions="", duration="5 days", fields_needing_review=[], user_confirmed=False)
    return SimpleNamespace(**{**base, **kw})


class ScheduleTests(APITestCase):
    def test_only_written_instructions_create_times(self):
        self.assertEqual(schedule_for(med(frequency="1-0-1"))["slots"], ["Morning", "Night"])
        self.assertEqual(schedule_for(med(frequency="1-1-1-1"))["slots"], ["Morning", "Afternoon", "Evening", "Night"])
        self.assertEqual(schedule_for(med(frequency="OD", timing="at bedtime"))["slots"], ["Night"])
        bd = schedule_for(med(frequency="BD"))
        self.assertEqual(bd["slots"], [])  # nothing presented as the doctor's instruction
        self.assertEqual(bd["suggested"], ["Morning", "Night"])  # typical meaning of BD, labelled for confirmation
        self.assertIn("confirm with your doctor or pharmacist", bd["note"])
        self.assertEqual(schedule_for(med(frequency="OD"))["suggested"], [])  # once-daily time depends on the medicine
        self.assertIn("when needed", schedule_for(med(frequency="SOS"))["note"])
        self.assertIn("not written", schedule_for(med(frequency=""))["note"])

    def test_schedule_table_sorted_by_time_of_day(self):
        s = build_schedule([med(frequency="0-0-1", line_number=1), med(name_as_written="Pantoprazole", frequency="1-0-0", line_number=2),
                            med(name_as_written="Cetirizine", frequency="BD", line_number=3)])
        written = [r["time"] for r in s["rows"] if not r["suggested"]]
        typical = [(r["time"], r["medicine"]) for r in s["rows"] if r["suggested"]]
        self.assertEqual(written, ["Morning", "Night"])
        self.assertEqual(typical, [("Morning", "Cetirizine 500 mg"), ("Night", "Cetirizine 500 mg")])
        self.assertEqual(s["unscheduled"][0]["medicine"], "Cetirizine 500 mg")


class SafetyTests(APITestCase):
    def test_missing_unreadable_duplicate_and_allergy(self):
        meds = [med(line_number=1, name_as_written="Metfrmn", fields_needing_review=["name"], strength="", duration=""),
                med(line_number=2, name_as_written="Amoxicillin", frequency="1-0-1"),
                med(line_number=3, name_as_written="Amoxicillin", frequency="1-0-1")]
        msgs = [w["message"] for w in safety_warnings(meds, allergies_text="Allergic to amoxicillin")]
        text = " ".join(msgs)
        self.assertIn("could not be read with certainty", text)
        self.assertIn("strength", text)
        self.assertIn("duration", text)
        self.assertIn("look like the same medicine", text)
        self.assertIn("matches an allergy", text)
        self.assertNotIn("stop", text.lower().replace("stopping", ""))  # never tells the user to stop a medicine

    def test_only_identified_names_are_looked_up(self):
        meds = [med(name_as_written="Metfrmn", generic_name=""),                      # guess: never looked up
                med(name_as_written="Glycomet", generic_name="metformin"),            # RxNorm exact match
                med(name_as_written="Dolo 650", generic_name="", user_confirmed=True)]  # user confirmed
        self.assertEqual(identified_names(meds), ["metformin", "Dolo 650"])


class InsightsEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice, self.bob = make_user("alice@example.com"), make_user("bob@example.com")
        self.rx = Prescription.objects.create(document=make_doc(self.alice, "prescription"))
        PrescriptionMedicine.objects.create(prescription=self.rx, line_number=1, name_as_written="Glycomet",
                                            generic_name="metformin", strength="500 mg", frequency="1-0-1", duration="10 days")
        PrescriptionMedicine.objects.create(prescription=self.rx, line_number=2, name_as_written="Xyzqv",
                                            fields_needing_review=["name"], frequency="BD")
        PatientProfile.objects.update_or_create(user=self.alice, defaults={"allergies": "none known"})
        self.client.force_authenticate(self.alice)

    def test_insights(self):
        info = {"medicines": [{"query": "metformin", "generic_name": "Metformin Hydrochloride", "uses": "glycemic control",
                               "source_url": "https://dailymed.nlm.nih.gov/x"}]}
        with mock.patch("core.ai_client.medicine_info", return_value=info) as m:
            res = self.client.get(f"/api/prescriptions/{self.rx.pk}/insights/")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        m.assert_called_once_with(["metformin"])  # the unreadable "Xyzqv" is never looked up
        rows = body["schedule"]["rows"]
        self.assertEqual([r["time"] for r in rows if not r["suggested"]], ["Morning", "Night"])   # written 1-0-1
        self.assertTrue(all(r["suggested"] for r in rows if r["line"] == 2))                     # "BD": typical only
        self.assertEqual(body["medicine_info"][0]["generic_name"], "Metformin Hydrochloride")
        self.assertIn("Xyzqv", body["unidentified"])
        self.assertTrue(any("could not be read" in w["message"] for w in body["safety"]))
        self.assertIn("pharmacist", body["disclaimer"])
        with mock.patch("core.ai_client.medicine_info") as m2:  # cached: no second call
            self.client.get(f"/api/prescriptions/{self.rx.pk}/insights/")
        m2.assert_not_called()

    def test_ai_offline_still_returns_schedule_and_safety(self):
        from core.ai_client import AIServiceError

        with mock.patch("core.ai_client.medicine_info", side_effect=AIServiceError("down")):
            body = self.client.get(f"/api/prescriptions/{self.rx.pk}/insights/").json()
        self.assertIn("unavailable", body["medicine_info_error"])
        self.assertTrue(body["schedule"]["rows"])

    def test_other_users_cannot_read(self):
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get(f"/api/prescriptions/{self.rx.pk}/insights/").status_code, 404)


class AddRemoveMedicineTests(APITestCase):
    def setUp(self):
        self.alice, self.bob = make_user("alice@example.com"), make_user("bob@example.com")
        self.rx = Prescription.objects.create(document=make_doc(self.alice, "prescription"))
        self.wrong = PrescriptionMedicine.objects.create(prescription=self.rx, line_number=1, name_as_written="ISHNAVI CLINIC")
        self.client.force_authenticate(self.alice)

    def test_user_adds_a_missed_medicine_and_removes_a_wrong_line(self):
        res = self.client.post(f"/api/prescriptions/{self.rx.pk}/medicines/",
                               {"name_as_written": "Pan 40", "strength": "40 mg", "frequency": "BD"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["line_number"], res.json()["user_confirmed"]), (2, True))
        self.assertEqual(self.client.delete(f"/api/prescriptions/{self.rx.pk}/medicines/{self.wrong.pk}/").status_code, 204)
        self.assertEqual(list(self.rx.medicines.values_list("name_as_written", flat=True)), ["Pan 40"])

    def test_validation_and_isolation(self):
        self.assertEqual(self.client.post(f"/api/prescriptions/{self.rx.pk}/medicines/", {"name_as_written": ""}, format="json").status_code, 400)
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.post(f"/api/prescriptions/{self.rx.pk}/medicines/", {"name_as_written": "X tab"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/prescriptions/{self.rx.pk}/medicines/{self.wrong.pk}/").status_code, 404)
