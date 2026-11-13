from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APITestCase

from core.models import AuditLog
from patients.models import PatientProfile

User = get_user_model()

VALID = {"email": "Asha@Example.com", "password": "Str0ng-pass-phrase", "first_name": "Asha", "last_name": "R"}


class AuthFlowTests(APITestCase):
    def test_register_login_me(self):
        res = self.client.post("/api/auth/register/", VALID, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertNotIn("password", res.json())
        self.assertEqual(res.json()["email"], "asha@example.com")

        res = self.client.post(
            "/api/auth/token/", {"email": "asha@example.com", "password": VALID["password"]}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        access = res.json()["access"]

        res = self.client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["first_name"], "Asha")

    def test_duplicate_email_rejected_case_insensitively(self):
        self.client.post("/api/auth/register/", VALID, format="json")
        res = self.client.post("/api/auth/register/", {**VALID, "email": "ASHA@example.com"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.json())

    def test_weak_password_rejected(self):
        res = self.client.post("/api/auth/register/", {**VALID, "password": "12345678"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_me_requires_auth(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)


class RegistrationContractTests(APITestCase):
    """The exact request the React form sends, and the error shapes the UI relies on."""

    URL = "/api/auth/register/"

    def test_frontend_payload_creates_user_profile_and_audit_entry(self):
        payload = {"first_name": "Ravi", "last_name": "Kumar", "email": "ravi.kumar@example.com", "password": "Clinic-visit-2026"}
        res = self.client.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(set(res.json()), {"id", "email", "first_name", "last_name"})
        user = User.objects.get(email="ravi.kumar@example.com")
        self.assertTrue(user.check_password("Clinic-visit-2026"))
        self.assertEqual(user.username, "ravi.kumar@example.com")
        self.assertTrue(PatientProfile.objects.filter(user=user).exists())
        self.assertTrue(AuditLog.objects.filter(action="register", resource_id=str(user.pk)).exists())

    def test_last_name_is_optional(self):
        res = self.client.post(self.URL, {**VALID, "last_name": ""}, format="json")
        self.assertEqual(res.status_code, 201, res.content)

    def test_duplicate_email_gives_one_clear_message(self):
        self.client.post(self.URL, VALID, format="json")
        for email in ("asha@example.com", "ASHA@EXAMPLE.COM", " asha@example.com "):
            with self.subTest(email=email):
                res = self.client.post(self.URL, {**VALID, "email": email}, format="json")
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.json()["email"], ["An account with this email already exists."])
                self.assertEqual(res.json()["code"], "invalid")
        self.assertEqual(User.objects.count(), 1)

    def test_simultaneous_duplicate_signup_is_400_not_500(self):
        with mock.patch.object(User.objects, "create_user", side_effect=IntegrityError("UNIQUE constraint failed")):
            res = self.client.post(self.URL, VALID, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.json())

    def test_missing_fields_are_reported_per_field(self):
        res = self.client.post(self.URL, {}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertTrue({"email", "password", "first_name"} <= set(res.json()))

    def test_blank_first_name_rejected(self):
        res = self.client.post(self.URL, {**VALID, "first_name": ""}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("first_name", res.json())

    def test_invalid_email_rejected(self):
        res = self.client.post(self.URL, {**VALID, "email": "not-an-email"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.json())

    def test_password_rules_reported_on_password_field(self):
        cases = {
            "short": "Ab1-x",
            "numeric": "8392047561",
            "common": "password123",
            "similar to email": "asha@example.com",
        }
        for label, password in cases.items():
            with self.subTest(label):
                res = self.client.post(self.URL, {**VALID, "password": password}, format="json")
                self.assertEqual(res.status_code, 400, res.content)
                self.assertIn("password", res.json())
                self.assertTrue(res.json()["password"][0])
        self.assertEqual(User.objects.count(), 0)

    def test_errors_are_json_not_html(self):
        res = self.client.post(self.URL, {}, format="json")
        self.assertEqual(res["Content-Type"], "application/json")

    def test_form_encoded_post_also_works(self):
        res = self.client.post(self.URL, VALID)  # multipart, in case a client doesn't send JSON
        self.assertEqual(res.status_code, 201, res.content)


class LoginAfterRegistrationTests(APITestCase):
    def setUp(self):
        self.client.post("/api/auth/register/", VALID, format="json")

    def test_can_sign_in_with_any_email_case(self):
        for email in ("asha@example.com", "Asha@Example.com", "  ASHA@EXAMPLE.COM "):
            with self.subTest(email=email):
                res = self.client.post("/api/auth/token/", {"email": email, "password": VALID["password"]}, format="json")
                self.assertEqual(res.status_code, 200, res.content)
                self.assertIn("access", res.json())
                self.assertIn("refresh", res.json())

    def test_wrong_password_rejected_with_detail(self):
        res = self.client.post("/api/auth/token/", {"email": "asha@example.com", "password": "wrong"}, format="json")
        self.assertEqual(res.status_code, 401)
        self.assertIn("detail", res.json())

    def test_refresh_token_works(self):
        tokens = self.client.post(
            "/api/auth/token/", {"email": "asha@example.com", "password": VALID["password"]}, format="json"
        ).json()
        res = self.client.post("/api/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.json())
