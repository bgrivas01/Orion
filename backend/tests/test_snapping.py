"""Snapping is a bounded, explicit proposal, never a route or access guarantee."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import httpx
import pytest
from fastapi import HTTPException
from app.config import Settings
from app.models import LatLng, RouteRequest, SnapProposal, SnapConfirmation
from app.routers import routes
from app.services import ors, risk, avoid_set

POINT = LatLng(lat=30.21, lon=-93.14)
ROAD = LatLng(lat=30.2105, lon=-93.14)

@pytest.fixture
def settings(monkeypatch):
    value = Settings(_env_file=None, ors_api_key="private-test-key", use_fixtures=False)
    monkeypatch.setattr(ors, "get_settings", lambda: value)
    monkeypatch.setattr(routes, "get_settings", lambda: value)
    return value


def transport(monkeypatch, status=200, body=None):
    requests = []
    original = httpx.AsyncClient
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    monkeypatch.setattr(ors.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    return requests


@pytest.mark.parametrize("kind", ["school", "airport", "university", "hospital", "business"])
async def test_poi_proposal_requires_confirmation(monkeypatch, settings, kind):
    # POI labels do not authorize access or change distance limits.
    requests = transport(monkeypatch, body={"locations":[{"location":[ROAD.lon,ROAD.lat]}]})
    request = RouteRequest(origin=POINT, destination=LatLng(lat=30.3,lon=-93.1))
    result = await routes._snap_proposal(request, ors.ORSLocationError("2010", (0,)))
    proposal = result.snap_proposals[0]
    assert result.routes == []
    assert proposal.original == POINT and proposal.proposed == ROAD
    assert 55 < proposal.distance_m < 57
    assert proposal.confirmation_required and not proposal.access_verified
    assert requests[0].url.path == "/openrouteservice/v2/snap/driving-car/json"
    assert requests[0].headers["Authorization"] == settings.ors_api_key
    assert settings.ors_api_key not in str(requests[0].url)
    assert json.loads(requests[0].content)["radius"] == 150


@pytest.mark.parametrize("location", [None, {"location":[-93.14,30.22]}, {"location":[POINT.lon,POINT.lat]}])
async def test_null_too_far_or_identical_points_require_manual_selection(monkeypatch, settings, location):
    transport(monkeypatch, body={"locations":[location]})
    with pytest.raises(HTTPException) as error:
        await routes._snap_proposal(RouteRequest(origin=POINT,destination=ROAD), ors.ORSLocationError("2010",(0,)))
    assert error.value.status_code == 422
    assert "entrance" in error.value.detail


@pytest.mark.parametrize("status,phrase", [(401,"credentials"),(403,"access denied"),(404,"unsupported"),(405,"unsupported"),(501,"unsupported"),(429,"quota"),(503,"service error")])
async def test_unsupported_and_permission_errors_are_safe(monkeypatch, settings, status, phrase):
    transport(monkeypatch,status,{"error":{"message":settings.ors_api_key}})
    with pytest.raises(ors.ORSError) as error:
        await ors.snap_points([POINT])
    assert phrase in str(error.value)
    assert settings.ors_api_key not in str(error.value)


@pytest.mark.parametrize("body", [{}, {"locations":[]},{"locations":[{}]}, {"locations":[{"location":[0]}]}, {"locations":[{"location":[900,900]}]}])
async def test_invalid_payload(monkeypatch, settings, body):
    transport(monkeypatch,body=body)
    with pytest.raises(ors.ORSUnavailable):
        await ors.snap_points([POINT])


@pytest.mark.parametrize("message,indices", [("Could not find point 1 within radius",(1,)),("Could not find routable point near specified coordinate 0",(0,)),("point 0; point 1",(0,1)),("private unrelated message",())])
def test_only_endpoint_index_is_extracted(message, indices):
    with pytest.raises(ors.ORSLocationError) as error:
        ors.response_data(httpx.Response(404,json={"error":{"code":2010,"message":message}}),"routing")
    assert error.value.endpoint_indices == indices
    assert message not in str(error.value)


async def test_unknown_endpoint_does_not_move_both_points(monkeypatch, settings):
    snap=AsyncMock()
    monkeypatch.setattr(ors,"snap_points",snap)
    with pytest.raises(HTTPException):
        await routes._snap_proposal(RouteRequest(origin=POINT,destination=ROAD),ors.ORSLocationError("2010"))
    snap.assert_not_called()


def accepted():
    return SnapConfirmation(endpoint="origin",original=POINT,proposed=ROAD,distance_m=ors.distance_m(POINT,ROAD),public_access_confirmed=True)


async def test_confirmed_point_cannot_bypass_missing_flood_engine(monkeypatch, settings):
    monkeypatch.setattr(routes.db,"pool",lambda: None)
    with pytest.raises(HTTPException) as error:
        await routes.plan_routes(RouteRequest(origin=ROAD,destination=POINT,accepted_snaps=[accepted()]))
    assert error.value.status_code == 503


async def test_accepted_point_is_not_snapped_again(monkeypatch, settings):
    snap=AsyncMock()
    monkeypatch.setattr(ors,"snap_points",snap)
    with pytest.raises(HTTPException):
        await routes._snap_proposal(RouteRequest(origin=ROAD,destination=POINT,accepted_snaps=[accepted()]),ors.ORSLocationError("2010",(0,)))
    snap.assert_not_called()


async def test_ordinary_routable_address_never_calls_snap(monkeypatch,settings):
    from app.models import LineString
    monkeypatch.setattr(routes.db,"pool",lambda: None)
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=ors.RouteResult(LineString(coordinates=[[-95.3,29.7,10],[-95.4,29.8,11]]),100,20)))
    snap=AsyncMock()
    monkeypatch.setattr(ors,"snap_points",snap)
    result=await routes.plan_routes(RouteRequest(origin=POINT,destination=ROAD))
    assert result.routes and not result.snap_proposals
    snap.assert_not_called()


async def test_confirmed_route_reassesses_warning_exposure(monkeypatch,settings):
    from app.models import LineString, RiskBreakdown, RiskBand
    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    monkeypatch.setattr(routes.db,"pool",lambda: SimpleNamespace(acquire=Connection))
    monkeypatch.setattr(avoid_set,"count_active_zones",AsyncMock(return_value=1))
    monkeypatch.setattr(avoid_set,"build",AsyncMock(return_value=avoid_set.AvoidSet(None,0,[])))
    geometry=LineString(coordinates=[[ROAD.lon,ROAD.lat,10],[POINT.lon,POINT.lat,10]])
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=ors.RouteResult(geometry,100,20)))
    assess=AsyncMock(return_value=risk.Assessment(breakdown=RiskBreakdown(flood_exposure=20,low_lying=0,gauge_proximity=0,approach_margin=0,total=20),band=RiskBand.CAUTION,flagged_segments=[],clear_of_flooding=False,warnings=["NWS warning area, road access unknown"]))
    monkeypatch.setattr(risk,"assess",assess)
    monkeypatch.setattr(routes,"_persist",AsyncMock())
    result=await routes.plan_routes(RouteRequest(origin=ROAD,destination=POINT,accepted_snaps=[accepted()]))
    assess.assert_awaited_once()
    assert assess.call_args.args[1] == geometry
    assert not result.routes[0].avoidance_verified
    assert result.accepted_snaps[0].original == POINT
    assert result.routes[0].warnings

async def test_configured_smaller_limit_is_enforced(monkeypatch, settings):
    settings.road_snap_limit_m = 20
    requests = transport(monkeypatch, body={"locations":[{"location":[ROAD.lon,ROAD.lat]}]})
    assert await ors.snap_points([POINT]) == [None]
    assert json.loads(requests[0].content)["radius"] == 20


async def test_confirmation_must_match_request_and_limit(monkeypatch, settings):
    confirmation = accepted()
    confirmation.proposed = LatLng(lat=31,lon=-93)
    with pytest.raises(HTTPException) as error:
        await routes.plan_routes(RouteRequest(origin=confirmation.proposed,destination=POINT,accepted_snaps=[confirmation]))
    assert error.value.status_code == 422


async def test_both_failed_endpoints_are_preserved(monkeypatch, settings):
    other = LatLng(lat=30.3,lon=-93.1)
    other_road = LatLng(lat=30.3005,lon=-93.1)
    transport(monkeypatch, body={"locations":[{"location":[ROAD.lon,ROAD.lat]},{"location":[other_road.lon,other_road.lat]}]})
    result = await routes._snap_proposal(RouteRequest(origin=POINT,destination=other),ors.ORSLocationError("2010",(0,1)))
    assert [p.endpoint for p in result.snap_proposals] == ["origin","destination"]
    assert [p.original for p in result.snap_proposals] == [POINT,other]


@pytest.fixture(autouse=True)
def isolate_candidate_search(monkeypatch):
    monkeypatch.setattr(ors, "alternatives", AsyncMock(return_value=[]))
    monkeypatch.setattr(avoid_set, "origin_in_warning", AsyncMock(return_value=False))
