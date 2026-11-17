from core.models import AuditLog
from documents.models import MedicalDocument
from documents.tests import DocumentTestBase


class AccountSettingsTests(DocumentTestBase):
    PW = "Str0ng-pass-phrase"

    def test_update_name_but_not_email(self):
        res = self.client.patch("/api/auth/me/", {"first_name": "Alicia", "email": "evil@example.com"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.first_name, "Alicia")
        self.assertEqual(self.alice.email, "alice@example.com")

    def test_change_password(self):
        bad = self.client.post("/api/auth/password/", {"current_password": "wrong", "new_password": "An0ther-long-phrase"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("current_password", bad.json())
        weak = self.client.post("/api/auth/password/", {"current_password": self.PW, "new_password": "12345678"}, format="json")
        self.assertEqual(weak.status_code, 400)
        ok = self.client.post("/api/auth/password/", {"current_password": self.PW, "new_password": "An0ther-long-phrase"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password("An0ther-long-phrase"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PASSWORD_CHANGE).exists())

    def test_delete_account_requires_password_and_removes_data(self):
        doc_id = self.upload().json()["id"]
        path = self.stored_path(doc_id)
        bob_doc = None
        self.client.force_authenticate(self.bob)
        bob_doc = self.upload(name="b.pdf", content=b"%PDF-1.7\n%bob\n%%EOF\n").json()["id"]
        self.client.force_authenticate(self.alice)

        self.assertEqual(self.client.delete("/api/auth/me/", {"password": "wrong"}, format="json").status_code, 400)
        self.assertTrue(path.exists())

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.delete("/api/auth/me/", {"password": self.PW}, format="json")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(MedicalDocument.objects.filter(pk=doc_id).exists())
        self.assertFalse(path.exists())
        self.assertTrue(MedicalDocument.objects.filter(pk=bob_doc).exists())  # other users untouched
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.ACCOUNT_DELETE).exists())

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/auth/password/", {}, format="json").status_code, 401)
        self.assertEqual(self.client.delete("/api/auth/me/", {"password": "x"}, format="json").status_code, 401)
