from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

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
