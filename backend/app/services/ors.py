"""OpenRouteService client: directions (with elevation) and geocoding.

Free-tier budget is 2,000 directions/day and 40/min, and we spend up to 3 calls
per route request, so callers should not retry blindly.
"""

import logging
import math
import re
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


class ORSLocationError(ORSError):
    """A selected point cannot be connected to the routing network."""

    def __init__(self, message: str, endpoint_indices: tuple[int, ...] = ()):
        super().__init__(message)
        self.endpoint_indices = endpoint_indices


class ORSNoRoute(ORSError):
    """The provider could not connect the selected locations."""


def error_code(response: httpx.Response) -> int | None:
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        return code if type(code) is int else None
    except ValueError:
        return None


def response_data(response: httpx.Response, service: str) -> dict[str, Any]:
    """Do not expose response bodies or request URLs, which may contain secrets."""
    status = response.status_code
    prefix = f"ORS {service}"
    code = error_code(response)
    if service == "routing" and status in (400, 404):
        if code == 2010:
            body = response.json()
            message = body.get("error", {}).get("message", "")
            indices = tuple(sorted({int(i) for i in re.findall(
                r"(?:point|coordinate)\s+([01])\b", message, re.IGNORECASE
            )})) if isinstance(message, str) else ()
            raise ORSLocationError("ORS routing: a selected location is not near a routable road (2010). Select a public-road entrance instead of a campus or airport centre.", indices)
        if code == 2009:
            raise ORSNoRoute("ORS routing: no connected route was found (2009). Check public-road entrances and access restrictions, or choose different locations.")
        if code == 2004:
            raise ORSError("ORS routing: request exceeds a provider limit (2004). The unmodified Fastest candidate is evaluated separately.")
        if status == 404:
            raise ORSError("ORS routing: unclassified upstream 404. Check the routing endpoint and sanitized diagnostic code; this does not establish a location or avoidance failure.")
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

    log.info(
        "ORS directions status=%d code=%s profile=%s avoidance=%s point_count=%d",
        r.status_code, error_code(r),
        path.split("/")[3] if path.split("/")[3] in ("driving-car", "cycling-regular", "foot-walking") else "other",
        bool(payload.get("options", {}).get("avoid_polygons")), len(payload.get("coordinates", [])),
    )
    return response_data(r, "routing")


async def directions(
    origin: LatLng,
    destination: LatLng,
    profile: str = "driving-car",
    avoid_polygons: dict[str, Any] | None = None,
    elevation: bool = True,
    preference: str | None = None,
    avoid_features: list[str] | None = None,
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

    if preference:
        payload["preference"] = preference
    if avoid_features:
        payload.setdefault("options", {})["avoid_features"] = avoid_features
    data = await _post(f"/v2/directions/{profile}/geojson", payload)

    return _route_results(data)[0]


def _route_results(data: dict[str, Any]) -> list[RouteResult]:
    features = data.get("features") or []
    if not features:
        raise ORSNoRoute("ORS routing returned no route. Choose public-road entrances or different locations.")
    routes = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if geometry.get("type") != "LineString" or len(coords) < 2:
            raise ORSError("ORS returned invalid route geometry")
        summary = (feature.get("properties") or {}).get("summary") or {}
        routes.append(RouteResult(LineString(coordinates=coords),
            float(summary.get("distance") or 0), float(summary.get("duration") or 0)))
    return routes


async def alternatives(origin: LatLng, destination: LatLng, profile: str = "driving-car") -> list[RouteResult]:
    data = await _post(f"/v2/directions/{profile}/geojson", {
        "coordinates": [[origin.lon, origin.lat], [destination.lon, destination.lat]],
        "elevation": True, "instructions": False,
        "alternative_routes": {"target_count": 3, "weight_factor": 1.4, "share_factor": 0.6},
    })
    return _route_results(data)[:3]


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


def distance_m(a: LatLng, b: LatLng) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(b.lon-a.lon)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


async def snap_points(points: list[LatLng]) -> list[LatLng | None]:
    """Bounded proposal lookup only; never infers building or public access."""
    settings = get_settings()
    if not settings.ors_api_key:
        raise ORSError("Road snapping is not configured. Select a public-road entrance.")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{settings.ors_base_url}/v2/snap/driving-car/json",
                headers={"Authorization": settings.ors_api_key, "Accept": "application/json"},
                json={"locations": [[p.lon, p.lat] for p in points], "radius": settings.road_snap_limit_m},
            )
    except httpx.HTTPError as exc:
        raise ORSUnavailable("Road snapping could not be reached. Select a public-road entrance.") from exc
    log.info("ORS snap status=%d code=%s point_count=%d", response.status_code, error_code(response), len(points))
    if response.status_code in (404, 405, 501):
        raise ORSError("Road snapping is unsupported by this service. Select a public-road entrance.")
    if not 200 <= response.status_code < 300:
        response_data(response, "snapping")  # Shared, sanitized credential/quota errors.
    try:
        locations = response.json()["locations"]
        if not isinstance(locations, list) or len(locations) != len(points):
            raise ValueError()
        result = []
        for original, location in zip(points, locations, strict=True):
            if location is None:
                result.append(None)
                continue
            coordinates = location["location"]
            if not isinstance(coordinates, list) or len(coordinates) != 2:
                raise ValueError()
            point = LatLng(lon=coordinates[0], lat=coordinates[1])
            moved = distance_m(original, point)
            result.append(point if 0.5 < moved <= settings.road_snap_limit_m else None)
        return result
    except (ValueError, TypeError, KeyError) as exc:
        raise ORSUnavailable("Road snapping returned invalid data. Select a public-road entrance.") from exc
