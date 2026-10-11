"""Contracts and ranking tests; synthetic fixtures do NOT prove live avoidance."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.models import FloodSeverity, RiskBand
from app.services import avoid_set, hazard_router, ors, risk
from app.routers import routes
from .test_candidates import setup, route, assessment


async def test_outside_warnings_zero_overlap_beats_shorter_route(setup, monkeypatch):
    monkeypatch.setattr(ors, "alternatives", AsyncMock(return_value=[route(.05,70000,5000)]))
    monkeypatch.setattr(risk,"assess",AsyncMock(side_effect=[assessment(30),assessment(0)]))
    response = await routes._plan(None,setup)
    best = response.routes[0]
    assert best.duration_s == 5000 and best.warning_avoidance_achieved
    assert response.recommended_id == best.id
    assert not response.no_lower_risk_route_found


async def test_trip_entirely_outside_warnings_needs_no_improvement(setup, monkeypatch):
    monkeypatch.setattr(avoid_set,"count_active_zones",AsyncMock(return_value=0))
    monkeypatch.setattr(risk,"assess",AsyncMock(return_value=assessment(0)))
    response = await routes._plan(None,setup)
    assert response.routes[0].warning_exposure_percent == 0
    assert response.recommended_id
    assert not response.no_lower_risk_route_found


@pytest.mark.parametrize("inside",[(True,False),(False,True),(True,True)])
async def test_endpoints_inside_warning_are_explained(setup, monkeypatch, inside):
    monkeypatch.setattr(avoid_set,"origin_in_warning",AsyncMock(side_effect=inside))
    response = await routes._plan(None,setup)
    assert any("origin is inside" in w for w in response.warnings) == inside[0]
    assert any("destination is inside" in w for w in response.warnings) == inside[1]


async def test_less_severe_and_shorter_exposure_wins_despite_display_score(setup,monkeypatch):
    severe, moderate = assessment(20),assessment(30)
    severe.warning_severity_m={"severe":6000}; severe.warning_exposure_m=6000
    moderate.warning_severity_m={"moderate":1000}; moderate.warning_exposure_m=1000
    monkeypatch.setattr(ors,"alternatives",AsyncMock(return_value=[route(.05)]))
    monkeypatch.setattr(risk,"assess",AsyncMock(side_effect=[severe,moderate]))
    response=await routes._plan(None,setup)
    assert response.routes[0].warning_severity_m == {"moderate":1000}
    assert response.recommended_id == response.routes[0].id


async def test_known_hazards_excluded_even_if_warning_exposure_zero(setup,monkeypatch):
    hazard = assessment(0); hazard.hazard_exposure_m=10
    monkeypatch.setattr(risk,"assess",AsyncMock(return_value=hazard))
    response=await routes._plan(None,setup)
    assert not response.routes and response.recommended_id is None
    assert routes.NO_LOWER_EXPOSURE in response.warnings


async def test_warning_avoidance_precedes_alternatives(setup,monkeypatch):
    polygon={"type":"MultiPolygon","coordinates":[]}
    monkeypatch.setattr(avoid_set,"build",AsyncMock(return_value=avoid_set.AvoidSet(polygon,1,[])))
    calls=[]
    async def directions(*args,**kwargs):
        calls.append(kwargs.get("avoid_polygons")); return route()
    async def alternatives(*args,**kwargs): calls.append("alternatives"); return []
    monkeypatch.setattr(ors,"directions",directions)
    monkeypatch.setattr(ors,"alternatives",alternatives)
    await routes._plan(None,setup)
    assert calls==[None,polygon,"alternatives"]
    assert avoid_set.build.call_args.kwargs["include_warnings"] is True


@pytest.mark.parametrize("failure",[False,True])
async def test_large_warning_uses_configured_road_engine_and_reassesses(setup,monkeypatch,failure):
    monkeypatch.setattr(routes,"get_settings",lambda:Settings(_env_file=None,hazard_router_url="http://router.test/route"))
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=route(distance=170000)))
    monkeypatch.setattr(avoid_set,"hazard_areas",AsyncMock(return_value=[{"source":"nws"}]))
    engine=AsyncMock(side_effect=ors.ORSUnavailable("unavailable")) if failure else AsyncMock(return_value=route(.05,200000,4500))
    monkeypatch.setattr(hazard_router,"route",engine)
    monkeypatch.setattr(risk,"assess",AsyncMock(side_effect=[assessment(30),assessment(0)]))
    response=await routes._plan(None,setup)
    engine.assert_awaited_once_with(setup.origin,setup.destination,[{"source":"nws"}],inside_warning=False)
    ors.alternatives.assert_not_awaited()
    assert risk.assess.await_count==(1 if failure else 2)
    assert response.no_lower_risk_route_found == failure


def test_no_2km_warning_plateau():
    scores=[risk.flood_exposure_score([risk.ExposureHit("x","Warning",FloodSeverity.SEVERE,m,source="nws")]) for m in (2000,6000,56000,80000)]
    assert scores==sorted(set(scores)) and scores[-1]<50


def test_early_exit_and_reentry_tiebreaks():
    from app.models import RouteCandidate,LineString
    a=RouteCandidate(id="a",label="alternative",geometry=LineString(coordinates=[[0,0],[1,1]]),distance_m=10000,duration_s=100,
        risk_score=20,risk_band=RiskBand.CAUTION,risk_breakdown=assessment(20).breakdown,
        warning_exposure_m=1000,warning_severity_m={"moderate":1000},initial_warning_exit_m=500,warning_reentries=1)
    b=a.model_copy(update={"initial_warning_exit_m":800,"duration_s":90})
    assert routes._exposure_key(a)<routes._exposure_key(b)
    b=a.model_copy(update={"warning_reentries":2})
    assert routes._exposure_key(a)<routes._exposure_key(b)


def test_screenshot_overlapping_intervals_35_1_not_50_1():
    mile=1609.344
    intervals=[(0,35.1*mile),(10*mile,25*mile)]
    assert sum(b-a for a,b in intervals)/mile == pytest.approx(50.1)
    assert sum(b-a for a,b in risk.union_intervals(intervals))/mile == pytest.approx(35.1)


async def test_assessment_joins_severity_boundaries_and_detects_reentry():
    # Already-exclusive SQL rows: the severity boundary at 200 m is NOT an exit.
    rows=[]
    for lo,hi,severity in [(0,.2,"severe"),(.2,.5,"moderate"),(.8,.9,"moderate")]:
        rows.append({"id":severity,"source":"nws","severity":severity,"event":"Warning",
            "seg":json.dumps({"coordinates":[[lo,0],[hi,0]]}),"len_m":(hi-lo)*1000,
            "edge":1,"lo":lo,"hi":hi,"edge_m":1000,"start_m":0,"route_m":1000})
    conn=AsyncMock(); conn.fetch.side_effect=[rows,[]]; conn.fetchval.return_value=0
    measured=await risk.assess(conn,route().geometry)
    assert measured.warning_exposure_m==pytest.approx(600)
    assert measured.warning_exposure_percent==pytest.approx(60)
    assert measured.initial_warning_exit_m==pytest.approx(500)
    assert measured.warning_reentries==1
    assert measured.warning_severity_m==pytest.approx({"severe":200,"moderate":400})


async def test_point_touch_is_not_claimed_as_complete_avoidance():
    conn=AsyncMock(); conn.fetch.side_effect=[[],[]]
    conn.fetchval.return_value=json.dumps({"nearest":0,"warning_intersection":True,"hazard_intersection":False})
    measured=await risk.assess(conn,route().geometry)
    assert measured.warning_exposure_m==0 and measured.warning_intersection
    assert not measured.clear_of_flooding
    assert any("touches a warning boundary" in w for w in measured.warnings)


async def test_reduced_terrain_alone_is_not_claimed_as_lower_warning_exposure(setup,monkeypatch):
    a,b=assessment(30),assessment(30)
    a.breakdown.low_lying=10
    monkeypatch.setattr(ors,"alternatives",AsyncMock(return_value=[route(.05)]))
    monkeypatch.setattr(risk,"assess",AsyncMock(side_effect=[a,b]))
    response=await routes._plan(None,setup)
    assert response.no_lower_risk_route_found and response.recommended_id is None


async def test_total_timeout_fails_without_returning_unassessed_route(setup,monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from unittest.mock import MagicMock
    monkeypatch.setattr(routes,"get_settings",lambda:Settings(_env_file=None,ors_api_key="test",routing_timeout_s=.01))
    pool=MagicMock(); pool.acquire.return_value.__aenter__=AsyncMock(return_value=None)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=False)
    monkeypatch.setattr(routes.db,"pool",lambda:pool)
    async def slow(*args): await asyncio.sleep(1)
    monkeypatch.setattr(routes,"_plan",slow)
    with pytest.raises(HTTPException) as error: await routes.plan_routes(setup)
    assert error.value.status_code==503 and "time budget" in error.value.detail


@pytest.fixture
def engine_http(monkeypatch):
    monkeypatch.setattr(hazard_router,"get_settings",lambda:Settings(_env_file=None,hazard_router_url="http://router.test/route"))
    requests=[]
    state={"status":200,"body":{"paths":[{"points":route().geometry.model_dump(),"distance":50000,"time":3600000}]}}
    client=httpx.AsyncClient
    def handle(request):
        requests.append(json.loads(request.content)); return httpx.Response(state["status"],json=state["body"])
    monkeypatch.setattr(hazard_router.httpx,"AsyncClient",lambda **kw:client(transport=httpx.MockTransport(handle),**kw))
    return requests,state


@pytest.mark.parametrize("inside",[False,True])
async def test_custom_model_blocks_hazards_and_weights_warning_severity(setup,engine_http,inside):
    areas=[{"source":source,"severity":severity,"geometry":json.dumps({"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]})}
           for source,severity in [("nws","moderate"),("road_closure","unknown"),("nws","severe")]]
    result=await hazard_router.route(setup.origin,setup.destination,areas,inside)
    payload=engine_http[0][0]; rules=payload["custom_model"]["priority"]
    assert payload["profile"]=="car" and payload["ch.disable"]
    assert "road_access" in rules[0]["if"] and rules[0]["multiply_by"]=="0"
    assert rules[1]["multiply_by"]=="0"
    assert [r["multiply_by"] for r in rules[2:]]==(["0.05","0.15"] if inside else ["0","0"])
    assert all("else_if" in r for r in rules[2:])
    assert result.geometry==route().geometry


@pytest.mark.parametrize("status",[400,401,403,404,429,500])
async def test_engine_service_errors_fail_closed(setup,engine_http,status):
    engine_http[1]["status"]=status
    with pytest.raises(ors.ORSUnavailable): await hazard_router.route(setup.origin,setup.destination,[])


async def test_engine_does_not_move_endpoints_or_send_partial_hazards(setup,engine_http):
    engine_http[1]["body"]["paths"][0]["points"]["coordinates"][0]=[-90,30]
    with pytest.raises(ors.ORSError,match="moved an endpoint"):
        await hazard_router.route(setup.origin,setup.destination,[])
    with pytest.raises(ors.ORSUnavailable,match="200-polygon"):
        await hazard_router.route(setup.origin,setup.destination,[{}]*201)
    assert len(engine_http[0])==1
