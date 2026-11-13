from rest_framework.test import APITestCase

from accounts.models import User
from core.models import AuditLog
from patients.models import PatientProfile


def make_user(email):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-phrase")


class ProfileTests(APITestCase):
    def setUp(self):
        self.alice = make_user("alice@example.com")
        self.bob = make_user("bob@example.com")

    def test_profile_created_automatically(self):
        self.assertTrue(PatientProfile.objects.filter(user=self.alice).exists())

    def test_get_and_patch_own_profile(self):
        self.client.force_authenticate(self.alice)
        res = self.client.patch(
            "/api/patients/me/profile/", {"sex": "female", "height_cm": "162.5", "allergies": "Penicillin"}, format="json"
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.client.get("/api/patients/me/profile/").json()["allergies"], "Penicillin")
        self.assertTrue(AuditLog.objects.filter(action="profile.update", user=self.alice).exists())

    def test_profiles_are_isolated(self):
        self.client.force_authenticate(self.alice)
        self.client.patch("/api/patients/me/profile/", {"allergies": "Penicillin"}, format="json")
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get("/api/patients/me/profile/").json()["allergies"], "")

    def test_validation(self):
        self.client.force_authenticate(self.alice)
        for payload in ({"height_cm": "5"}, {"date_of_birth": "2999-01-01"}, {"sex": "robot"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch("/api/patients/me/profile/", payload, format="json").status_code, 400)

    def test_requires_auth(self):
        self.assertEqual(self.client.get("/api/patients/me/profile/").status_code, 401)
