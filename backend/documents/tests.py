import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import User
from core.models import AuditLog
from documents import tasks as doc_tasks
from documents.models import MedicalDocument, ProcessingTask

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def make_user(email):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-phrase", first_name="T")


class DocumentTestBase(APITestCase):
    # Tests must not depend on the developer's .env (which may enable processing locally).
    processing_enabled = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix="ayumitra-test-media-")
        cls._override = override_settings(MEDIA_ROOT=cls._media, PRIVATE_MEDIA_ROOT=Path(cls._media),
                                          DOCUMENT_PROCESSING_ENABLED=cls.processing_enabled)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.alice = make_user("alice@example.com")
        self.bob = make_user("bob@example.com")
        self.client.force_authenticate(self.alice)

    def upload(self, name="report.pdf", content=PDF, **extra):
        data = {"file": SimpleUploadedFile(name, content, content_type="application/octet-stream"), **extra}
        return self.client.post("/api/documents/upload/", data, format="multipart")

    def stored_path(self, doc_id):
        return Path(self._media) / MedicalDocument.objects.get(pk=doc_id).file.name


class UploadTests(DocumentTestBase):
    def test_authenticated_pdf_upload(self):
        res = self.upload(document_type="lab_report", title="CBC March")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual(body["original_filename"], "report.pdf")
        self.assertEqual(body["content_type"], "application/pdf")
        self.assertEqual(body["document_type"], "lab_report")
        self.assertEqual(body["status"], "uploaded")
        self.assertEqual(body["file_size"], len(PDF))
        self.assertNotIn("file", body)  # storage path is never exposed
        self.assertTrue(body["file_url"].startswith("/api/documents/"))
        self.assertTrue(self.stored_path(body["id"]).exists())
        self.assertTrue(AuditLog.objects.filter(action="document.upload", resource_id=body["id"]).exists())

    def test_png_and_jpeg_accepted(self):
        for name, content, ctype in [("a.png", PNG, "image/png"), ("b.jpg", JPEG, "image/jpeg"), ("c.JPEG", JPEG + b"1", "image/jpeg")]:
            with self.subTest(name=name):
                res = self.upload(name, content)
                self.assertEqual(res.status_code, 201, res.content)
                self.assertEqual(res.json()["content_type"], ctype)

    def test_stored_filename_is_random_and_scoped_to_owner(self):
        res = self.upload("HIV test result.pdf")
        path = MedicalDocument.objects.get(pk=res.json()["id"]).file.name
        self.assertTrue(path.startswith(f"documents/{self.alice.pk}/"))
        self.assertNotIn("HIV", path)
        self.assertRegex(Path(path).name, r"^[0-9a-f]{32}\.pdf$")

    def test_unauthenticated_upload_rejected(self):
        self.client.force_authenticate(None)
        res = self.upload()
        self.assertEqual(res.status_code, 401)
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_disallowed_extension_rejected(self):
        res = self.upload("notes.docx", b"PK\x03\x04whatever")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.json())

    def test_spoofed_content_rejected(self):
        # Right extension, wrong bytes (e.g. an executable renamed to .pdf).
        res = self.upload("report.pdf", b"MZ\x90\x00 this is not a pdf")
        self.assertEqual(res.status_code, 400)
        self.assertIn("not a valid PDF", str(res.json()["file"]))

    def test_extension_content_mismatch_rejected(self):
        res = self.upload("scan.png", PDF)
        self.assertEqual(res.status_code, 400)
        self.assertIn("does not match", str(res.json()["file"]))

    def test_empty_file_rejected(self):
        res = self.upload("empty.pdf", b"")
        self.assertEqual(res.status_code, 400)

    def test_missing_file_rejected(self):
        res = self.client.post("/api/documents/upload/", {"document_type": "lab_report"}, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.json())

    def test_invalid_document_type_rejected(self):
        res = self.upload(document_type="xray_of_my_cat")
        self.assertEqual(res.status_code, 400)
        self.assertIn("document_type", res.json())

    @override_settings(DOCUMENT_MAX_UPLOAD_MB=1)
    def test_file_size_limit(self):
        res = self.upload("big.pdf", PDF + b"0" * (1024 * 1024))
        self.assertIn(res.status_code, (400, 413))
        self.assertIn("too large", str(res.json()))
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_duplicate_upload_returns_conflict(self):
        first = self.upload().json()["id"]
        res = self.upload("copy.pdf")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["duplicate_of"], first)

    def test_same_file_for_different_users_is_not_a_duplicate(self):
        self.upload()
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.upload().status_code, 201)


class IsolationTests(DocumentTestBase):
    """Cross-user access must be indistinguishable from a missing document (404)."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.bob)
        self.bobs_doc = self.upload("bob.pdf").json()["id"]
        self.client.force_authenticate(self.alice)

    def test_list_only_shows_own_documents(self):
        self.upload("alice.pdf", PDF + b"a")
        res = self.client.get("/api/documents/")
        self.assertEqual(res.status_code, 200)
        names = [d["original_filename"] for d in res.json()["results"]]
        self.assertEqual(names, ["alice.pdf"])

    def test_cannot_retrieve_other_users_document(self):
        self.assertEqual(self.client.get(f"/api/documents/{self.bobs_doc}/").status_code, 404)

    def test_cannot_read_other_users_status(self):
        self.assertEqual(self.client.get(f"/api/documents/{self.bobs_doc}/status/").status_code, 404)

    def test_cannot_download_other_users_file(self):
        self.assertEqual(self.client.get(f"/api/documents/{self.bobs_doc}/file/").status_code, 404)

    def test_cannot_modify_other_users_document(self):
        res = self.client.patch(f"/api/documents/{self.bobs_doc}/", {"title": "pwned"}, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(MedicalDocument.objects.get(pk=self.bobs_doc).title, "")

    def test_cannot_delete_other_users_document(self):
        self.assertEqual(self.client.delete(f"/api/documents/{self.bobs_doc}/").status_code, 404)
        self.assertTrue(MedicalDocument.objects.filter(pk=self.bobs_doc).exists())
        self.assertTrue(self.stored_path(self.bobs_doc).exists())

    def test_unauthenticated_cannot_list_or_read(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/documents/").status_code, 401)
        self.assertEqual(self.client.get(f"/api/documents/{self.bobs_doc}/file/").status_code, 401)

    def test_no_public_media_url(self):
        path = MedicalDocument.objects.get(pk=self.bobs_doc).file.name
        self.client.force_authenticate(None)
        for url in (f"/media/{path}", f"/{path}", f"/private_media/{path}"):
            self.assertEqual(self.client.get(url).status_code, 404, url)


class DocumentApiTests(DocumentTestBase):
    def test_list_pagination_and_filters(self):
        self.upload("a.pdf", PDF + b"1", document_type="lab_report")
        self.upload("b.pdf", PDF + b"2", document_type="prescription")
        body = self.client.get("/api/documents/").json()
        self.assertEqual(body["count"], 2)
        self.assertEqual([d["original_filename"] for d in body["results"]], ["b.pdf", "a.pdf"])  # newest first
        only = self.client.get("/api/documents/?document_type=prescription").json()
        self.assertEqual([d["original_filename"] for d in only["results"]], ["b.pdf"])

    def test_retrieve_and_status(self):
        doc = self.upload().json()["id"]
        self.assertEqual(self.client.get(f"/api/documents/{doc}/").json()["id"], doc)
        status_body = self.client.get(f"/api/documents/{doc}/status/").json()
        self.assertEqual(status_body["status"], "uploaded")
        self.assertFalse(status_body["processing_enabled"])
        self.assertEqual(status_body["tasks"], [])

    def test_owner_can_download_file_with_safe_headers(self):
        doc = self.upload().json()["id"]
        res = self.client.get(f"/api/documents/{doc}/file/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(b"".join(res.streaming_content), PDF)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertEqual(res["Cache-Control"], "private, no-store")
        self.assertEqual(res["X-Content-Type-Options"], "nosniff")
        self.assertTrue(AuditLog.objects.filter(action="document.view", resource_id=doc).exists())

    def test_patch_editable_fields_only(self):
        doc = self.upload().json()["id"]
        res = self.client.patch(
            f"/api/documents/{doc}/", {"title": "Lipid panel", "document_type": "lab_report", "status": "completed"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["title"], "Lipid panel")
        self.assertEqual(res.json()["status"], "uploaded")  # read-only, ignored

    def test_delete_removes_row_and_file(self):
        doc = self.upload().json()["id"]
        path = self.stored_path(doc)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.delete(f"/api/documents/{doc}/")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(MedicalDocument.objects.filter(pk=doc).exists())
        self.assertFalse(path.exists())
        self.assertTrue(AuditLog.objects.filter(action="document.delete", resource_id=doc).exists())

    def test_deleting_account_removes_files(self):
        doc = self.upload().json()["id"]
        path = self.stored_path(doc)
        with self.captureOnCommitCallbacks(execute=True):
            self.alice.delete()
        self.assertFalse(path.exists())

    def test_unknown_document_is_404_json(self):
        res = self.client.get("/api/documents/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "not_found")

    def test_malformed_id_is_404(self):
        self.assertEqual(self.client.get("/api/documents/not-a-uuid/").status_code, 404)

    def test_put_not_allowed(self):
        doc = self.upload().json()["id"]
        self.assertEqual(self.client.put(f"/api/documents/{doc}/", {}, format="json").status_code, 405)


@override_settings(DOCUMENT_PROCESSING_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=True)
class ProcessingPipelineTests(DocumentTestBase):
    """The Celery plumbing, exercised eagerly (no Redis needed) with test-only steps."""

    processing_enabled = True

    def setUp(self):
        super().setUp()
        from config.celery import app

        app.conf.task_always_eager = True
        self.addCleanup(setattr, app.conf, "task_always_eager", False)
        self._saved = list(doc_tasks.PIPELINE)
        self.addCleanup(lambda: doc_tasks.PIPELINE.__init__(self._saved))

    def test_no_steps_reports_honestly_instead_of_completed(self):
        doc_tasks.PIPELINE.clear()
        with self.captureOnCommitCallbacks(execute=True):
            doc = self.upload().json()["id"]
        status_body = self.client.get(f"/api/documents/{doc}/status/").json()
        self.assertEqual(status_body["status"], "uploaded")
        self.assertEqual(status_body["tasks"][0]["status"], "succeeded")
        self.assertIn("No processing steps", status_body["tasks"][0]["message"])

    def test_steps_run_and_progress_is_tracked(self):
        def fake_ocr(document, report):
            report(50, "halfway")

        doc_tasks.PIPELINE[:] = [(ProcessingTask.TaskType.OCR, fake_ocr)]
        with self.captureOnCommitCallbacks(execute=True):
            doc = self.upload().json()["id"]
        body = self.client.get(f"/api/documents/{doc}/status/").json()
        self.assertEqual(body["status"], "completed")
        types = {t["task_type"]: t for t in body["tasks"]}
        self.assertEqual(types["ocr"]["status"], "succeeded")
        self.assertEqual(types["ingest"]["progress"], 100)

    def test_failing_step_marks_document_failed(self):
        def broken(document, report):
            raise RuntimeError("OCR engine crashed")

        doc_tasks.PIPELINE[:] = [(ProcessingTask.TaskType.OCR, broken)]
        with self.captureOnCommitCallbacks(execute=True):
            doc = self.upload().json()["id"]
        body = self.client.get(f"/api/documents/{doc}/status/").json()
        self.assertEqual(body["status"], "failed")
        self.assertTrue(body["error_message"])
        self.assertNotIn("OCR engine crashed", body["error_message"])  # internals not shown to the user
        self.assertEqual({t["task_type"]: t["status"] for t in body["tasks"]}["ocr"], "failed")
