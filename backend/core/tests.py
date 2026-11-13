from django.test import TestCase


class HealthTests(TestCase):
    def test_health_is_public(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_bad_credentials_rejected(self):
        res = self.client.post("/api/auth/token/", {"email": "x@y.z", "password": "nope"})
        self.assertEqual(res.status_code, 401)
