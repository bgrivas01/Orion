"""OpenRouteService client: directions (with elevation) and geocoding.

Free-tier budget is 2,000 directions/day and 40/min, and we spend up to 3 calls
per route request, so callers should not retry blindly.
"""

import logging
from typing import Any

import httpx

from ..config import get_settings
from ..models import LatLng, LineString

log = logging.getLogger(__name__)


class ORSError(RuntimeError):
    """ORS refused or failed a request."""


class ORSUnavailable(ORSError):
    """ORS could not be reached, or rate-limited us."""


class RouteResult:
    """One route as ORS returned it, before any of our own scoring."""

    def __init__(self, geometry: LineString, distance_m: float, duration_s: float):
        self.geometry = geometry
        self.distance_m = distance_m
        self.duration_s = duration_s

    @property
    def has_elevation(self) -> bool:
        return bool(self.geometry.coordinates) and len(self.geometry.coordinates[0]) > 2


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.ors_api_key:
        raise ORSError("ORS_API_KEY is not configured")

    url = f"{settings.ors_base_url}{path}"
    headers = {
        "Authorization": settings.ors_api_key,
        "Content-Type": "application/json",
        "Accept": "application/geo+json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise ORSUnavailable(f"ORS request failed: {exc}") from exc

    if r.status_code == 429:
        raise ORSUnavailable("ORS rate limit hit (40/min, 2000/day on the free tier)")
    if r.status_code >= 500:
        raise ORSUnavailable(f"ORS server error {r.status_code}")
    if r.status_code >= 400:
        # ORS puts a useful reason in the body — surface it, it is usually a
        # violated avoid-polygon limit.
        raise ORSError(f"ORS rejected the request ({r.status_code}): {r.text[:400]}")

    return r.json()


async def directions(
    origin: LatLng,
    destination: LatLng,
    profile: str = "driving-car",
    avoid_polygons: dict[str, Any] | None = None,
    elevation: bool = True,
) -> RouteResult:
    """Fetch one route.

    `avoid_polygons` is a GeoJSON Polygon/MultiPolygon dict. ORS honours it
    unreliably — the caller must verify the result independently.
    """
    payload: dict[str, Any] = {
        "coordinates": [[origin.lon, origin.lat], [destination.lon, destination.lat]],
        "elevation": elevation,
        "instructions": False,
    }
    if avoid_polygons:
        payload["options"] = {"avoid_polygons": avoid_polygons}

    data = await _post(f"/v2/directions/{profile}/geojson", payload)

    features = data.get("features") or []
    if not features:
        raise ORSError("ORS returned no route")

    feature = features[0]
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if not coords:
        raise ORSError("ORS returned an empty geometry")

    summary = (feature.get("properties") or {}).get("summary") or {}
    return RouteResult(
        geometry=LineString(coordinates=coords),
        distance_m=float(summary.get("distance") or 0.0),
        duration_s=float(summary.get("duration") or 0.0),
    )


async def geocode(text: str, limit: int = 6) -> list[dict[str, Any]]:
    """Pelias autocomplete, restricted to the US (our data coverage)."""
    settings = get_settings()
    if not settings.ors_api_key:
        raise ORSError("ORS_API_KEY is not configured")

    params = {
        "api_key": settings.ors_api_key,
        "text": text,
        "boundary.country": "US",
        "size": str(limit),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{settings.ors_base_url}/geocode/autocomplete", params=params)
    except httpx.HTTPError as exc:
        raise ORSUnavailable(f"geocoding failed: {exc}") from exc

    if r.status_code >= 400:
        raise ORSError(f"geocoding rejected ({r.status_code})")

    out = []
    for feat in (r.json().get("features") or []):
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        out.append(
            {
                "name": props.get("label") or props.get("name") or text,
                "lon": coords[0],
                "lat": coords[1],
                "region": props.get("region"),
            }
        )
    return out
