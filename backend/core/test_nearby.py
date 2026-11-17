import io
import urllib.error
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from core import nearby

PLACE = [{"display_name": "Noida, Uttar Pradesh, India", "lat": "28.5355", "lon": "77.3910"}]
ELEMENTS = {"elements": [
    {"type": "node", "id": 1, "lat": 28.5400, "lon": 77.3910,
     "tags": {"amenity": "hospital", "name": "Test Hospital", "phone": "+91 120 000 0000", "addr:city": "Noida"}},
    {"type": "way", "id": 2, "center": {"lat": 28.5400, "lon": 77.3911},
     "tags": {"amenity": "hospital", "name": "Test Hospital"}},          # same place mapped twice
    {"type": "node", "id": 3, "lat": 28.5360, "lon": 77.3912, "tags": {"amenity": "pharmacy", "name": "Test Chemist"}},
    {"type": "node", "id": 4, "lat": 28.5370, "lon": 77.3920, "tags": {"amenity": "clinic"}},  # no name: skipped
]}


def fake_urlopen(responses):
    """Each call pops the next response: a dict -> JSON body, an int -> HTTPError with that code."""
    def _open(req, timeout=None):
        r = responses.pop(0)
        if isinstance(r, int):
            raise urllib.error.HTTPError(req.full_url, r, "busy", {}, None)
        body = io.BytesIO(__import__("json").dumps(r).encode())
        body.__enter__ = lambda *a: body
        body.__exit__ = lambda *a: False
        return body
    return _open


@override_settings(OVERPASS_URLS=["https://a.example/api", "https://b.example/api"])
class NearbyTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="u@example.com", email="u@example.com", password="Str0ng-pass-phrase")
        self.client.force_authenticate(self.user)

    def get(self, **params):
        return self.client.get("/api/care/nearby/", {"city": "Noida", "radius": 5, **params})

    def test_requires_login_and_validates_input(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.get().status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.get(city="").status_code, 400)
        self.assertEqual(self.get(radius=7).status_code, 400)
        self.assertEqual(self.get(category="spa").status_code, 400)

    def test_results_are_real_parsed_deduplicated_and_sorted(self):
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen([PLACE, ELEMENTS])):
            res = self.get()
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual([f["name"] for f in body["facilities"]], ["Test Chemist", "Test Hospital"])  # by distance
        hosp = body["facilities"][1]
        self.assertEqual((hosp["category"], hosp["phone"], hosp["website"]), ("hospital", "+91 120 000 0000", ""))
        self.assertGreater(hosp["distance_km"], 0)
        self.assertIn("OpenStreetMap", body["attribution"])

    def test_repeated_search_is_cached(self):
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen([PLACE, ELEMENTS])) as m:
            self.get()
            res = self.get()
        self.assertTrue(res.json()["cached"])
        self.assertEqual(m.call_count, 2)  # one geocode + one Overpass call in total

    def test_unknown_city(self):
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen([[]])):
            res = self.get(city="Qwertyuiopville")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "place_not_found")

    def test_busy_server_falls_back_to_next_mirror(self):
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen([PLACE, 429, ELEMENTS])):
            res = self.get()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 2)

    def test_all_servers_down_gives_clear_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen([PLACE, 504, 429])):
            res = self.get()
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["code"], "map_service_unavailable")

    def test_hanging_mirror_does_not_block_a_working_one(self):
        def _open(req, timeout=None):
            if "a.example" in req.full_url:
                raise TimeoutError("timed out")
            return fake_urlopen([ELEMENTS])(req)
        with mock.patch("core.nearby.geocode", return_value={"name": "Noida", "lat": 28.5355, "lon": 77.3910}),                 mock.patch("urllib.request.urlopen", side_effect=_open):
            res = self.get()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 2)

    def test_all_category_query_uses_one_scan_per_key(self):
        q = nearby._overpass_query(28.5, 77.3, 5000, "all")
        self.assertEqual(q.count("around:"), 3)  # amenity, healthcare, shop
        self.assertIn('"amenity"~"^(hospital|clinic|pharmacy|doctors)$"', q)

    def test_category_filter_builds_specific_query(self):
        q = nearby._overpass_query(28.5, 77.3, 5000, "pharmacy")
        self.assertIn('"amenity"="pharmacy"', q)
        self.assertNotIn("hospital", q)
