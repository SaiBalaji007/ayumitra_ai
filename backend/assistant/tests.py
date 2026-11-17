"""Integration of Django with the AI service (mocked at the HTTP client boundary)."""

import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import User
from assistant.models import ChatMessage, Conversation
from core.ai_client import AIServiceError
from documents import tasks as doc_tasks
from documents.models import MedicalDocument, ProcessingTask
from medical_reports.models import ExtractedReport, LabParameter
from prescriptions.models import Prescription

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

ANALYSIS = {
    "extraction": {"content_type": "application/pdf", "page_count": 1, "warnings": [], "pages": [
        {"page_number": 1, "text": "Haemoglobin 10.2 L g/dL 12.0 - 15.5\nSerum Creatinine 1.0 mg/dL 0.6 - 1.2",
         "method": "text_layer", "confidence": None, "lines": [], "tables": [], "width": 595, "height": 842}]},
    "classification": {"document_type": "lab_report", "confidence": 0.9, "scores": {}, "cues": {}},
    "lab_results": [
        {"name_as_printed": "Haemoglobin", "normalized_name": "hemoglobin", "value_text": "10.2", "value_numeric": "10.2",
         "unit": "g/dL", "reference_range_text": "12.0 - 15.5", "reference_low": "12.0", "reference_high": "15.5",
         "lab_flag": "low", "confidence": 1.0, "page": 1},
        {"name_as_printed": "Serum Creatinine", "normalized_name": "creatinine", "value_text": "1.0", "value_numeric": "1.0",
         "unit": "mg/dL", "reference_range_text": "0.6 - 1.2", "reference_low": "0.6", "reference_high": "1.2",
         "lab_flag": "", "confidence": 1.0, "page": 1},
    ],
    "prescription_items": [],
    "versions": {"service": "test"},
}

RX_ANALYSIS = {
    **ANALYSIS,
    "classification": {"document_type": "prescription", "confidence": 0.8, "scores": {}, "cues": {}},
    "lab_results": [],
    "prescription_items": [
        {"line_number": 1, "name_as_written": "Metformin", "strength": "500 mg", "dosage_form": "tablet",
         "frequency": "1-0-1", "timing": "after food", "duration": "30 days", "route": "",
         "frequency_reading": "1 in the morning, 1 in the night",
         "medicine": {"status": "exact_ingredient", "generic_name": "metformin", "rxcui": "6809", "suggestions": []},
         "field_confidence": {"name": 1.0}, "overall_confidence": 0.95, "fields_needing_review": []},
        {"line_number": 2, "name_as_written": "Metfromin", "strength": "500 mg", "dosage_form": "tablet",
         "frequency": "", "timing": "", "duration": "", "route": "", "frequency_reading": "",
         "medicine": {"status": "suggestion", "generic_name": "", "rxcui": "",
                      "suggestions": [{"name": "metformin", "rxcui": "6809", "kind": "ingredient", "similarity": 0.89}]},
         "field_confidence": {"name": 0.6}, "overall_confidence": 0.6, "fields_needing_review": ["name", "frequency", "duration"]},
    ],
}


def make_user(email):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-phrase", first_name="T")


class Base(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix="ayumitra-test-")
        cls._ov = override_settings(MEDIA_ROOT=cls._media, PRIVATE_MEDIA_ROOT=Path(cls._media),
                                    DOCUMENT_PROCESSING_ENABLED=True, DOCUMENT_QUEUE_BACKEND="db")
        cls._ov.enable()

    @classmethod
    def tearDownClass(cls):
        cls._ov.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.alice, self.bob = make_user("alice@example.com"), make_user("bob@example.com")
        self.client.force_authenticate(self.alice)
        self._saved = list(doc_tasks.PIPELINE)
        doc_tasks.PIPELINE.clear()
        doc_tasks.register_default_pipeline()
        self.addCleanup(lambda: doc_tasks.PIPELINE.__init__(self._saved))

    def upload_and_process(self, analysis=ANALYSIS, name="r.pdf", doc_type="unknown"):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post("/api/documents/upload/",
                                   {"file": SimpleUploadedFile(name, PDF + name.encode()), "document_type": doc_type},
                                   format="multipart")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["status"], "queued")
        with mock.patch("documents.analysis.analyze_document", return_value=analysis):
            call_command("process_documents", "--once", stdout=StringIO())
        return res.json()["id"]


class DocumentPipelineTests(Base):
    def test_db_worker_processes_and_stores_structured_results(self):
        doc_id = self.upload_and_process()
        doc = MedicalDocument.objects.get(pk=doc_id)
        self.assertEqual(doc.status, "completed")
        self.assertEqual(doc.document_type, "lab_report")  # unknown -> filled from classification
        self.assertEqual(doc.page_count, 1)
        report = ExtractedReport.objects.get(document=doc)
        hb = report.parameters.get(normalized_name="hemoglobin")
        self.assertEqual((hb.value_text, hb.unit, hb.reference_range_text, hb.lab_flag), ("10.2", "g/dL", "12.0 - 15.5", "low"))
        ext = self.client.get(f"/api/documents/{doc_id}/extraction/").json()
        self.assertEqual(ext["pages"][0]["method"], "text_layer")
        self.assertEqual(ext["suggested_type"], "lab_report")

    def test_user_chosen_type_is_never_overridden(self):
        doc_id = self.upload_and_process(doc_type="discharge_summary")
        doc = MedicalDocument.objects.get(pk=doc_id)
        self.assertEqual(doc.document_type, "discharge_summary")
        self.assertEqual(doc.suggested_type, "lab_report")

    def test_ai_service_failure_marks_failed_without_leaking_details(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post("/api/documents/upload/", {"file": SimpleUploadedFile("x.pdf", PDF + b"x")}, format="multipart")
        with mock.patch("documents.analysis.analyze_document", side_effect=AIServiceError("connection refused")):
            call_command("process_documents", "--once", stdout=StringIO())
        body = self.client.get(f"/api/documents/{res.json()['id']}/status/").json()
        self.assertEqual(body["status"], "failed")
        self.assertNotIn("connection refused", str(body))

    def test_reprocess_replaces_previous_extraction(self):
        doc_id = self.upload_and_process()
        with mock.patch("documents.analysis.analyze_document", return_value=ANALYSIS):
            self.assertEqual(self.client.post(f"/api/documents/{doc_id}/reprocess/").status_code, 202)
            call_command("process_documents", "--once", stdout=StringIO())
        self.assertEqual(ExtractedReport.objects.filter(document_id=doc_id).count(), 1)
        self.assertEqual(LabParameter.objects.filter(report__document_id=doc_id).count(), 2)

    def test_worker_claims_each_job_once(self):
        self.upload_and_process()
        self.assertFalse(ProcessingTask.objects.filter(status="pending").exists())
        with mock.patch("documents.analysis.analyze_document") as m:
            call_command("process_documents", "--once", stdout=StringIO())
        m.assert_not_called()

    def test_other_users_cannot_reprocess_or_read_extraction(self):
        doc_id = self.upload_and_process()
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get(f"/api/documents/{doc_id}/extraction/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/documents/{doc_id}/reprocess/").status_code, 404)


class ReportIntelligenceTests(Base):
    def setUp(self):
        super().setUp()
        self.doc_id = self.upload_and_process()
        self.report = ExtractedReport.objects.get(document_id=self.doc_id)

    def test_report_api_shows_range_status_and_abnormal_count(self):
        body = self.client.get(f"/api/reports/{self.report.pk}/").json()
        status = {p["name_as_printed"]: p["range_status"] for p in body["parameters"]}
        self.assertEqual(status, {"Haemoglobin": "below", "Serum Creatinine": "within"})
        self.assertEqual(body["abnormal_count"], 1)

    def test_explain_sends_only_this_users_results_and_stores_answer(self):
        fake = {"explanations": [{"parameter": "Haemoglobin", "answer": {"status": "answered", "answer": "x [1]"}}],
                "messages": []}
        with mock.patch("medical_reports.views.run_agent", return_value=fake) as m:
            res = self.client.post(f"/api/reports/{self.report.pk}/explain/")
        self.assertEqual(res.status_code, 200)
        sent = m.call_args.args[0]["lab_results"]
        self.assertEqual({p["name_as_printed"] for p in sent}, {"Haemoglobin", "Serum Creatinine"})
        self.assertNotIn("alice", str(sent))  # no identity sent to the AI service
        self.assertEqual(self.client.get(f"/api/reports/{self.report.pk}/").json()["explanations"][0]["parameter"], "Haemoglobin")

    def test_education_endpoint(self):
        fake = {"explanations": [{"parameter": "Haemoglobin", "answer": {"status": "insufficient_evidence"}}],
                "messages": ["This is general education from trusted sources, not a personal diet or exercise plan."]}
        with mock.patch("medical_reports.views.run_agent", return_value=fake) as m:
            res = self.client.post(f"/api/reports/{self.report.pk}/education/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(m.call_args.args[0]["mode"], "education")
        self.assertEqual(self.client.get(f"/api/reports/{self.report.pk}/").json()["education"]["items"][0]["parameter"], "Haemoglobin")
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.post(f"/api/reports/{self.report.pk}/education/").status_code, 404)

    def test_pdf_export_is_owner_only_and_audited(self):
        from core.models import AuditLog

        with mock.patch("medical_reports.views.render_report_pdf", return_value=b"%PDF-1.7 test") as m:
            res = self.client.get(f"/api/reports/{self.report.pk}/export/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertEqual({p["name_as_printed"] for p in m.call_args.args[0]["parameters"]}, {"Haemoglobin", "Serum Creatinine"})
        self.assertTrue(AuditLog.objects.filter(action="report.export", resource_id=str(self.report.pk)).exists())
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get(f"/api/reports/{self.report.pk}/export/").status_code, 404)

    def test_explain_reports_ai_outage_cleanly(self):
        with mock.patch("medical_reports.views.run_agent", side_effect=AIServiceError("down")):
            res = self.client.post(f"/api/reports/{self.report.pk}/explain/")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["code"], "ai_unavailable")
        self.assertIn("unavailable", res.json()["detail"])

    def test_user_can_correct_a_value_which_re_derives_numbers(self):
        hb = self.report.parameters.get(normalized_name="hemoglobin")
        res = self.client.patch(f"/api/reports/{self.report.pk}/parameters/{hb.pk}/",
                                {"value_text": "12.4", "reference_range_text": "12.0 - 15.5"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["range_status"], "within")
        self.assertTrue(res.json()["user_verified"])

    def test_cannot_edit_printed_lab_flag_or_other_users_params(self):
        hb = self.report.parameters.get(normalized_name="hemoglobin")
        self.client.patch(f"/api/reports/{self.report.pk}/parameters/{hb.pk}/", {"lab_flag": "high"}, format="json")
        hb.refresh_from_db()
        self.assertEqual(hb.lab_flag, "low")
        self.client.force_authenticate(self.bob)
        res = self.client.patch(f"/api/reports/{self.report.pk}/parameters/{hb.pk}/", {"value_text": "1"}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_timeline(self):
        self.upload_and_process(name="second.pdf")
        names = self.client.get("/api/timeline/").json()
        self.assertEqual(names[0]["count"], 2)
        series = self.client.get("/api/timeline/?parameter=hemoglobin").json()
        self.assertEqual(len(series["points"]), 2)
        self.assertEqual(series["units"], ["g/dL"])
        self.assertFalse(series["mixed_units"])
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get("/api/timeline/?parameter=hemoglobin").json()["points"], [])


class PrescriptionVerificationTests(Base):
    def setUp(self):
        super().setUp()
        doc_id = self.upload_and_process(analysis=RX_ANALYSIS, name="rx.pdf")
        self.rx = Prescription.objects.get(document_id=doc_id)
        self.good, self.unsure = self.rx.medicines.order_by("line_number")

    def test_uncertain_medicine_has_no_generic_until_user_chooses(self):
        self.assertEqual(self.good.generic_name, "metformin")
        self.assertEqual(self.unsure.generic_name, "")
        self.assertEqual(self.unsure.fields_needing_review, ["name", "frequency", "duration"])

    def test_cannot_verify_until_all_lines_confirmed(self):
        res = self.client.post(f"/api/prescriptions/{self.rx.pk}/verify/")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "unconfirmed_lines")

    def test_correct_choose_suggestion_confirm_and_verify(self):
        url = f"/api/prescriptions/{self.rx.pk}/medicines/{self.unsure.pk}/"
        res = self.client.patch(url, {"choose_suggestion": "Metformin", "name_as_written": "Metformin",
                                      "frequency": "1-0-1", "duration": "30 days", "user_confirmed": True}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.unsure.refresh_from_db()
        self.assertEqual(self.unsure.generic_name, "metformin")
        self.assertEqual(self.unsure.fields_needing_review, [])
        self.client.patch(f"/api/prescriptions/{self.rx.pk}/medicines/{self.good.pk}/", {"user_confirmed": True}, format="json")
        res = self.client.post(f"/api/prescriptions/{self.rx.pk}/verify/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["user_verified"])

    def test_generic_name_cannot_be_invented(self):
        url = f"/api/prescriptions/{self.rx.pk}/medicines/{self.unsure.pk}/"
        res = self.client.patch(url, {"choose_suggestion": "Wonderdrug"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.patch(url, {"generic_name": "wonderdrug"}, format="json")  # not an editable field
        self.unsure.refresh_from_db()
        self.assertEqual(self.unsure.generic_name, "")

    def test_isolation(self):
        self.client.force_authenticate(self.bob)
        url = f"/api/prescriptions/{self.rx.pk}/medicines/{self.good.pk}/"
        self.assertEqual(self.client.patch(url, {"user_confirmed": True}, format="json").status_code, 404)
        self.assertEqual(self.client.post(f"/api/prescriptions/{self.rx.pk}/verify/").status_code, 404)


class AssistantTests(Base):
    AGENT_ANSWER = {"intent": "medical_question", "messages": [],
                    "answer": {"status": "answered", "answer": "HbA1c reflects average blood sugar. [1]",
                               "citations": [{"id": "1", "title": "Hemoglobin A1C (HbA1c) Test", "url": "https://medlineplus.gov/x",
                                              "section": "What is it?", "quote": "..."}],
                               "safety": {"flags": [], "urgent": False}}}

    def test_ask_creates_conversation_and_messages(self):
        with mock.patch("assistant.views.run_agent", return_value=self.AGENT_ANSWER):
            res = self.client.post("/api/assistant/ask/", {"question": "What is HbA1c?"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual(body["message"]["citations"][0]["title"], "Hemoglobin A1C (HbA1c) Test")
        convo = Conversation.objects.get(pk=body["conversation_id"])
        self.assertEqual(list(convo.messages.values_list("role", flat=True)), ["user", "assistant"])
        with mock.patch("assistant.views.run_agent", return_value=self.AGENT_ANSWER) as m:
            self.client.post("/api/assistant/ask/", {"question": "And is it fasting?", "conversation_id": str(convo.pk)}, format="json")
        self.assertEqual(convo.messages.count(), 4)
        # follow-ups carry this conversation's previous question (and nothing else)
        self.assertEqual(m.call_args.args[0]["previous_question"], "What is HbA1c?")
        self.assertEqual(m.call_args.args[0]["question"], "And is it fasting?")

    def test_report_chat_sends_own_results_only(self):
        doc_id = self.upload_and_process()
        report = ExtractedReport.objects.get(document_id=doc_id)
        with mock.patch("assistant.views.run_agent", return_value=self.AGENT_ANSWER) as m:
            self.client.post("/api/assistant/ask/", {"question": "Should I worry?", "report_id": report.pk}, format="json")
        self.assertEqual(len(m.call_args.args[0]["report_results"]), 2)
        self.client.force_authenticate(self.bob)
        with mock.patch("assistant.views.run_agent", return_value=self.AGENT_ANSWER) as m:
            res = self.client.post("/api/assistant/ask/", {"question": "Should I worry?", "report_id": report.pk}, format="json")
        self.assertEqual(res.status_code, 404)
        m.assert_not_called()

    def test_conversations_are_private(self):
        with mock.patch("assistant.views.run_agent", return_value=self.AGENT_ANSWER):
            cid = self.client.post("/api/assistant/ask/", {"question": "What is HbA1c?"}, format="json").json()["conversation_id"]
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get(f"/api/assistant/conversations/{cid}/").status_code, 404)
        self.assertEqual(self.client.get("/api/assistant/conversations/").json()["results"], [])
        with mock.patch("assistant.views.run_agent", return_value=self.AGENT_ANSWER):
            res = self.client.post("/api/assistant/ask/", {"question": "hi there doc", "conversation_id": cid}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_ai_outage_is_recorded_and_reported(self):
        with mock.patch("assistant.views.run_agent", side_effect=AIServiceError("down")):
            res = self.client.post("/api/assistant/ask/", {"question": "What is HbA1c?"}, format="json")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(ChatMessage.objects.filter(status="error").count(), 1)

    def test_validation(self):
        self.assertEqual(self.client.post("/api/assistant/ask/", {"question": "x"}, format="json").status_code, 400)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/assistant/ask/", {"question": "What is HbA1c?"}, format="json").status_code, 401)
