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


class ORSCredentialsError(ORSError):
    """Upstream authentication failed (401)."""


class ORSAccessDenied(ORSError):
    """Upstream refused access (403); credential validity may be ambiguous."""


class ORSRateLimited(ORSUnavailable):
    """Upstream quota or rate limit exhausted (429)."""


def response_data(response: httpx.Response, service: str) -> dict[str, Any]:
    """Do not expose response bodies or request URLs, which may contain secrets."""
    status = response.status_code
    prefix = f"ORS {service}"
    if status == 401:
        raise ORSCredentialsError(f"{prefix}: invalid or missing API credentials (401). Check the server-side ORS_API_KEY.")
    if status == 403:
        raise ORSAccessDenied(f"{prefix}: access denied (403). Check API permissions and key validity in the HeiGIT dashboard.")
    if status == 429:
        raise ORSRateLimited(f"{prefix}: rate limit or quota exceeded (429). Retry later or check your HeiGIT quota.")
    if status >= 500:
        raise ORSUnavailable(f"{prefix}: upstream service error ({status}).")
    if not 200 <= status < 300:
        raise ORSError(f"{prefix}: request rejected ({status}).")
    try:
        data = response.json()
    except ValueError as exc:
        raise ORSUnavailable(f"{prefix}: invalid JSON response.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise ORSUnavailable(f"{prefix}: invalid GeoJSON response.")
    return data


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
        raise ORSUnavailable("ORS routing service could not be reached") from exc

    return response_data(r, "routing")


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
        "text": text,
        "boundary.country": "US",
        "size": str(limit),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{settings.geocoding_base_url.rstrip('/')}/autocomplete",
                params=params, headers={"Authorization": settings.ors_api_key},
            )
    except httpx.HTTPError as exc:
        raise ORSUnavailable("ORS geocoding service could not be reached") from exc

    data = response_data(r, "geocoding")

    out = []
    for feat in (data.get("features") or []):
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
