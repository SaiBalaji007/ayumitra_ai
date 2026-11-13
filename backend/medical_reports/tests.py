from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from accounts.models import User
from documents.models import MedicalDocument
from medical_reports.models import ExtractedReport, LabParameter, MedicalFinding
from prescriptions.models import Prescription, PrescriptionMedicine


def make_user(email):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-phrase")


def make_doc(owner, doc_type):
    # Rows only; no file needed to test API isolation of extracted records.
    return MedicalDocument.objects.create(
        owner=owner, file=f"documents/{owner.pk}/x.pdf", original_filename="x.pdf",
        content_type="application/pdf", file_size=1, sha256="0" * 64, document_type=doc_type,
    )


class ExtractedRecordIsolationTests(APITestCase):
    def setUp(self):
        self.alice, self.bob = make_user("alice@example.com"), make_user("bob@example.com")
        self.reports = {}
        self.rx = {}
        for user in (self.alice, self.bob):
            report = ExtractedReport.objects.create(document=make_doc(user, "lab_report"), lab_name=f"{user.email} lab")
            LabParameter.objects.create(report=report, name_as_printed="Hemoglobin", value_text="13.8", unit="g/dL")
            MedicalFinding.objects.create(document=report.document, category="note", text=f"{user.email} note")
            rx = Prescription.objects.create(document=make_doc(user, "prescription"))
            PrescriptionMedicine.objects.create(prescription=rx, name_as_written=f"{user.email} med")
            self.reports[user.pk], self.rx[user.pk] = report, rx
        self.client.force_authenticate(self.alice)

    def test_reports_scoped_to_owner(self):
        body = self.client.get("/api/reports/").json()
        self.assertEqual([r["lab_name"] for r in body["results"]], ["alice@example.com lab"])
        self.assertEqual(body["results"][0]["parameters"][0]["value_text"], "13.8")
        self.assertEqual(self.client.get(f"/api/reports/{self.reports[self.bob.pk].pk}/").status_code, 404)

    def test_findings_scoped_to_owner(self):
        texts = [f["text"] for f in self.client.get("/api/findings/").json()["results"]]
        self.assertEqual(texts, ["alice@example.com note"])
        bob_doc = self.reports[self.bob.pk].document_id
        self.assertEqual(self.client.get(f"/api/findings/?document={bob_doc}").json()["results"], [])

    def test_prescriptions_scoped_to_owner(self):
        body = self.client.get("/api/prescriptions/").json()
        self.assertEqual([m["name_as_written"] for p in body["results"] for m in p["medicines"]], ["alice@example.com med"])
        self.assertEqual(self.client.get(f"/api/prescriptions/{self.rx[self.bob.pk].pk}/").status_code, 404)

    def test_extracted_records_are_read_only(self):
        self.assertEqual(self.client.post("/api/reports/", {}, format="json").status_code, 405)
        self.assertEqual(self.client.post("/api/prescriptions/", {}, format="json").status_code, 405)
        rid = self.reports[self.alice.pk].pk
        self.assertEqual(self.client.delete(f"/api/reports/{rid}/").status_code, 405)

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        for url in ("/api/reports/", "/api/findings/", "/api/prescriptions/"):
            self.assertEqual(self.client.get(url).status_code, 401, url)


class ModelIntegrityTests(APITestCase):
    def test_reference_range_low_cannot_exceed_high(self):
        report = ExtractedReport.objects.create(document=make_doc(make_user("c@example.com"), "lab_report"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            LabParameter.objects.create(
                report=report, name_as_printed="Glucose", value_text="90",
                reference_low=Decimal("100"), reference_high=Decimal("70"),
            )

    def test_one_report_per_document(self):
        doc = make_doc(make_user("d@example.com"), "lab_report")
        ExtractedReport.objects.create(document=doc)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExtractedReport.objects.create(document=doc)
