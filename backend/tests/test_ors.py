"""HTTP contract checks without a database, scheduler, or real credentials."""
import json

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.models import LatLng
from app.routers import geocode, health, routes
from app.services import ors

KEY = "test-secret-never-return"
ROUTE = {"features": [{"geometry": {"type": "LineString", "coordinates": [
    [-95.3698, 29.7604, 10], [-95.3698, 29.7634, 12]]},
    "properties": {"summary": {"distance": 350, "duration": 60}}}]}
PLACES = {"features": [{"geometry": {"coordinates": [-95.3698, 29.7604]},
    "properties": {"label": "Houston, TX", "region": "Texas"}}]}


@pytest.fixture
def upstream(monkeypatch):
    settings = Settings(_env_file=None, ors_api_key=KEY, use_fixtures=False)
    for module in (ors, geocode, health, routes):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(health.db, "pool", lambda: None)
    requests = []
    state = {"status": 200, "body": None}
    real_client = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        if state["status"] != 200:
            return httpx.Response(state["status"], text=KEY)
        body = state["body"]
        if body is None:
            body = PLACES if request.url.path.endswith("autocomplete") else ROUTE
        return httpx.Response(200, json=body)

    monkeypatch.setattr(ors.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    return state, requests, real_client


async def test_geocode_contract(upstream):
    _, requests, _ = upstream
    assert await ors.geocode("Houston") == [
        {"name": "Houston, TX", "region": "Texas", "lon": -95.3698, "lat": 29.7604}]
    request = requests[0]
    assert str(request.url).startswith("https://api.heigit.org/pelias/v1/autocomplete?")
    assert request.url.params["text"] == "Houston"
    assert request.url.params["boundary.country"] == "US"
    assert request.headers["Authorization"] == KEY
    assert KEY not in str(request.url)
    assert "api_key" not in request.url.params


async def test_directions_contract(upstream):
    _, requests, _ = upstream
    avoid = {"type": "Polygon", "coordinates": []}
    result = await ors.directions(LatLng(lat=29, lon=-95), LatLng(lat=30, lon=-94), avoid_polygons=avoid)
    assert result.distance_m == 350
    assert result.duration_s == 60
    assert result.has_elevation
    request = requests[0]
    assert str(request.url) == "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson"
    assert request.headers["Authorization"] == KEY
    assert json.loads(request.content) == {"coordinates": [[-95, 29], [-94, 30]],
        "elevation": True, "instructions": False, "options": {"avoid_polygons": avoid}}


@pytest.mark.parametrize("status,exception,phrase", [
    (401, ors.ORSCredentialsError, "credentials"),
    (403, ors.ORSAccessDenied, "access denied"),
    (429, ors.ORSRateLimited, "quota"),
    (503, ors.ORSUnavailable, "upstream service error"),
    (400, ors.ORSError, "request rejected"),
    (302, ors.ORSError, "request rejected"),
])
@pytest.mark.parametrize("service", ["geocode", "directions"])
async def test_safe_upstream_errors(upstream, status, exception, phrase, service):
    state, _, _ = upstream
    state["status"] = status
    with pytest.raises(exception) as error:
        if service == "geocode":
            await ors.geocode("Houston")
        else:
            await ors.directions(LatLng(lat=29, lon=-95), LatLng(lat=30, lon=-94))
    assert phrase in str(error.value)
    assert KEY not in str(error.value)


@pytest.mark.parametrize("status,expected", [(200, 200), (401, 502), (403, 502), (429, 503), (503, 503)])
@pytest.mark.parametrize("path", ["/api/geocode?q=Houston", "/api/routes"])
async def test_api_responses(upstream, status, expected, path):
    state, _, client_type = upstream
    state["status"] = status
    app = FastAPI()
    app.include_router(geocode.router)
    app.include_router(routes.router)
    async with client_type(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        if path == "/api/routes":
            response = await client.post(path, json={"origin": {"lat": 29, "lon": -95},
                "destination": {"lat": 30, "lon": -94}})
        else:
            response = await client.get(path)
    assert response.status_code == expected, response.text
    assert KEY not in response.text
    if status != 200:
        assert str(status) in response.json()["detail"]


@pytest.mark.parametrize("status,healthy", [(200, True), (401, False), (403, False), (429, False), (500, False)])
async def test_health_requires_success(upstream, status, healthy):
    state, requests, _ = upstream
    state["status"] = status
    result = await health.health()
    assert result.ors is healthy
    assert KEY not in (result.detail or "")
    assert not any(r.url.path.endswith("/health") for r in requests)
    if healthy:
        assert len(requests) == 2
    else:
        assert str(status) in result.detail


@pytest.mark.parametrize("body", [[], {"error": KEY}, {"features": "invalid"}])
async def test_bad_success_payload(upstream, body):
    upstream[0]["body"] = body
    with pytest.raises(ors.ORSUnavailable, match="invalid GeoJSON"):
        await ors.geocode("Houston")


def test_legacy_config_migrates_without_env_edits():
    settings = Settings(_env_file=None, ors_base_url="https://api.openrouteservice.org/")
    assert settings.ors_base_url == "https://api.heigit.org/openrouteservice"
    assert settings.geocoding_base_url == "https://api.heigit.org/pelias/v1"

async def test_network_error_is_sanitized(upstream, monkeypatch):
    _, _, real_client = upstream
    def fail(request):
        raise httpx.ConnectError(KEY, request=request)
    monkeypatch.setattr(ors.httpx, "AsyncClient", lambda **kwargs:
        real_client(transport=httpx.MockTransport(fail), **kwargs))
    for call in (ors.geocode("Houston"), ors.directions(LatLng(lat=29, lon=-95), LatLng(lat=30, lon=-94))):
        with pytest.raises(ors.ORSUnavailable) as error:
            await call
        assert KEY not in str(error.value)
        assert "could not be reached" in str(error.value)


async def test_health_fails_when_only_geocoding_denied(upstream, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ors, "geocode", AsyncMock(side_effect=ors.ORSAccessDenied("geocoding access denied (403)")))
    result = await health.health()
    assert result.ors is False
    assert "403" in result.detail


async def test_invalid_json_is_sanitized(upstream, monkeypatch):
    _, _, real_client = upstream
    monkeypatch.setattr(ors.httpx, "AsyncClient", lambda **kwargs:
        real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=KEY)), **kwargs))
    with pytest.raises(ors.ORSUnavailable, match="invalid JSON"):
        await ors.geocode("Houston")


@pytest.mark.parametrize("exception,status", [(ors.ORSRateLimited("quota exceeded (429)"), 503),
                                             (ors.ORSAccessDenied("access denied (403)"), 502)])
async def test_scored_routing_preserves_failure_reason(upstream, monkeypatch, exception, status):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from app.models import RouteRequest
    monkeypatch.setattr(routes.avoid_set_svc, "count_active_zones", AsyncMock(return_value=0))
    monkeypatch.setattr(ors, "directions", AsyncMock(side_effect=exception))
    request = RouteRequest(origin=LatLng(lat=29, lon=-95), destination=LatLng(lat=30, lon=-94))
    with pytest.raises(HTTPException) as error:
        await routes._plan(None, request)
    assert error.value.status_code == status
    assert str(exception) in error.value.detail
