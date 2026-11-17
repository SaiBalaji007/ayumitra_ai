"""
Nearby hospitals, clinics, doctors and pharmacies from OpenStreetMap (Phase 2).

  GET /api/care/nearby/?city=Noida&locality=Sector 18&category=all|hospital|clinic|pharmacy|doctor&radius=5

1. Nominatim turns "locality, city" into coordinates (the city/locality centre, not the user's location).
2. Overpass returns OSM medical facilities within the radius; all configured mirrors are asked in parallel
   and the first successful answer wins, so a 429/504 or a hanging server doesn't block the search.
Results are cached (24 h) so repeated searches don't hit the community servers again. Only data present in
OSM is returned: missing phone/hours/website stay empty and the UI shows "Not available".
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import math
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

log = logging.getLogger(__name__)

RADII_KM = (2, 5, 10, 20)
CACHE_S = 24 * 3600
# OSM tags per category (amenity=* and the newer healthcare=* scheme)
CATEGORY_TAGS = {
    "hospital": [("amenity", "hospital"), ("healthcare", "hospital")],
    "clinic": [("amenity", "clinic"), ("healthcare", "clinic")],
    "pharmacy": [("amenity", "pharmacy"), ("healthcare", "pharmacy"), ("shop", "chemist")],
    "doctor": [("amenity", "doctors"), ("healthcare", "doctor")],
}


class UpstreamError(Exception):
    pass


def _get_json(url: str, *, data: bytes | None = None, timeout: float = 25):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": settings.OSM_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode(city: str, locality: str = "") -> dict | None:
    q = ", ".join(p for p in (locality.strip(), city.strip()) if p)
    key = f"geo:{q.lower()}"
    if (hit := cache.get(key)) is not None:
        return hit or None
    url = settings.GEOCODER_URL + "?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "in"})
    try:
        rows = _get_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise UpstreamError(f"geocoder: {exc}") from exc
    place = {"name": rows[0]["display_name"], "lat": float(rows[0]["lat"]), "lon": float(rows[0]["lon"])} if rows else {}
    cache.set(key, place, CACHE_S)
    return place or None


def _overpass_query(lat: float, lon: float, radius_m: int, category: str) -> str:
    cats = CATEGORY_TAGS if category == "all" else {category: CATEGORY_TAGS[category]}
    by_key: dict[str, list[str]] = {}
    for tags in cats.values():
        for k, v in tags:
            by_key.setdefault(k, []).append(v)
    # One radius scan per OSM key (amenity / healthcare / shop) instead of one per tag: a third of the work,
    # which is what lets busy public servers answer at all.
    parts = "".join(
        f'nwr["{k}"="{vs[0]}"](around:{radius_m},{lat},{lon});' if len(vs) == 1
        else f'nwr["{k}"~"^({"|".join(vs)})$"](around:{radius_m},{lat},{lon});'
        for k, vs in by_key.items())
    return f"[out:json][timeout:25];({parts});out center tags 300;"


OVERPASS_TIMEOUT_S = 35


def _overpass_one(url: str, query: str) -> list[dict]:
    return _get_json(url, data=urllib.parse.urlencode({"data": query}).encode(),
                     timeout=OVERPASS_TIMEOUT_S).get("elements", [])


def overpass(query: str) -> list[dict]:
    """Ask every configured mirror at once and use the first answer, so one slow or broken server
    (frequent on the free public instances) no longer adds its full timeout to the user's wait."""
    urls = list(settings.OVERPASS_URLS)
    pool = ThreadPoolExecutor(max_workers=len(urls))
    futures = {pool.submit(_overpass_one, url, query): url for url in urls}
    errors = []
    try:
        for fut in as_completed(futures):
            try:
                return fut.result()
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                errors.append(f"{urllib.parse.urlsplit(futures[fut]).netloc}: {exc}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    raise UpstreamError("all Overpass servers failed: " + "; ".join(errors))


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _category(tags: dict) -> str:
    for cat, pairs in CATEGORY_TAGS.items():
        if any(tags.get(k) == v for k, v in pairs):
            return cat
    return "clinic"


def _address(tags: dict) -> str:
    if tags.get("addr:full"):
        return tags["addr:full"]
    parts = [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:suburb") or tags.get("addr:place"),
             tags.get("addr:city"), tags.get("addr:postcode")]
    return ", ".join(p for p in parts if p)


def to_facilities(elements: list[dict], lat: float, lon: float) -> list[dict]:
    out, seen = [], set()
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name") or tags.get("name:en") or "").strip()
        plat = el.get("lat") or (el.get("center") or {}).get("lat")
        plon = el.get("lon") or (el.get("center") or {}).get("lon")
        if not name or plat is None or plon is None:
            continue  # unnamed or unlocated features aren't useful to show
        key = (name.lower(), round(plat, 3), round(plon, 3))  # same place mapped as node + building
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": f"{el.get('type')}/{el.get('id')}", "name": name, "category": _category(tags),
            "address": _address(tags), "lat": plat, "lon": plon,
            "distance_km": round(_distance_km(lat, lon, plat, plon), 2),
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "website": tags.get("website") or tags.get("contact:website") or "",
            "opening_hours": tags.get("opening_hours") or "",
            "emergency": tags.get("emergency") == "yes",
        })
    out.sort(key=lambda f: f["distance_km"])
    return out


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def nearby(request):
    city = (request.query_params.get("city") or "").strip()
    locality = (request.query_params.get("locality") or "").strip()
    category = (request.query_params.get("category") or "all").strip().lower()
    try:
        radius = int(request.query_params.get("radius") or 5)
    except ValueError:
        radius = -1
    if not (2 <= len(city) <= 100) or len(locality) > 100:
        return Response({"detail": "Enter a city name (2–100 characters).", "code": "invalid_city"}, status=400)
    if category not in ("all", *CATEGORY_TAGS):
        return Response({"detail": "Unknown category.", "code": "invalid_category"}, status=400)
    if radius not in RADII_KM:
        return Response({"detail": "Radius must be 2, 5, 10 or 20 km.", "code": "invalid_radius"}, status=400)

    key = f"near:{city.lower()}|{locality.lower()}|{category}|{radius}"
    if (hit := cache.get(key)) is not None:
        return Response({**hit, "cached": True})
    try:
        place = geocode(city, locality)
        if place is None:
            return Response({"detail": f"Couldn't find \"{', '.join(p for p in (locality, city) if p)}\". Check the spelling.",
                             "code": "place_not_found"}, status=404)
        facilities = to_facilities(overpass(_overpass_query(place["lat"], place["lon"], radius * 1000, category)),
                                   place["lat"], place["lon"])
    except UpstreamError as exc:
        log.warning("Nearby search failed: %s", exc)
        return Response({"detail": "The map service is busy or unreachable right now. Please try again in a minute.",
                         "code": "map_service_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    body = {"place": place, "radius_km": radius, "category": category, "count": len(facilities),
            "facilities": facilities, "attribution": "Data © OpenStreetMap contributors (ODbL)"}
    cache.set(key, body, CACHE_S)
    return Response({**body, "cached": False})
