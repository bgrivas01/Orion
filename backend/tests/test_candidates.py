"""Provider-backed candidate generation: no invented detour geometry."""
from unittest.mock import AsyncMock
import pytest
from app.config import Settings
from app.models import LatLng, LineString, RouteRequest, RiskBand, RiskBreakdown, RoutePreference
from app.routers import routes
from app.services import ors, risk, avoid_set


def route(offset=0, distance=50000, duration=3600):
    return ors.RouteResult(LineString(coordinates=[[-93.37,30.23,10],[-92.7,30.23+offset,10],[-92.02,30.22,10]]),distance,duration)


def assessment(score):
    return risk.Assessment(breakdown=RiskBreakdown(flood_exposure=score,low_lying=0,gauge_proximity=0,approach_margin=0,total=score),band=RiskBand.DANGEROUS if score>=50 else RiskBand.CAUTION,flagged_segments=[],clear_of_flooding=score==0,warning_exposure_m=score*100,warning_severity_m={"severe":score*100})


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(routes,"get_settings",lambda:Settings(_env_file=None))
    monkeypatch.setattr(avoid_set,"count_active_zones",AsyncMock(return_value=1))
    monkeypatch.setattr(avoid_set,"origin_in_warning",AsyncMock(return_value=False))
    monkeypatch.setattr(avoid_set,"build",AsyncMock(return_value=avoid_set.AvoidSet(None,0,[])))
    monkeypatch.setattr(routes,"_persist",AsyncMock())
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=route()))
    monkeypatch.setattr(ors,"alternatives",AsyncMock(return_value=[]))
    monkeypatch.setattr(risk,"assess",AsyncMock(return_value=assessment(80)))
    return RouteRequest(origin=LatLng(lat=30.23,lon=-93.37),destination=LatLng(lat=30.22,lon=-92.02))


async def test_short_trip_evaluates_distinct_routes_with_identical_time_distance(setup,monkeypatch):
    monkeypatch.setattr(ors,"alternatives",AsyncMock(return_value=[route(),route(.05),route(-.05)]))
    monkeypatch.setattr(risk,"assess",AsyncMock(side_effect=[assessment(80),assessment(20),assessment(35)]))
    result=await routes._plan(None,setup)
    assert len(result.routes)==3
    assert risk.assess.await_count==3
    assert next(c for c in result.routes if c.id==result.recommended_id).risk_score==20
    assert not result.no_lower_risk_route_found
    ors.alternatives.assert_awaited_once()


async def test_sulphur_lafayette_long_trip_does_not_claim_generic_options_avoid_warnings(setup,monkeypatch):
    monkeypatch.setattr(ors,"directions",AsyncMock(side_effect=[route(distance=135000),route(.05,150000,4500),route(-.05,160000,4800)]))
    monkeypatch.setattr(risk,"assess",AsyncMock(side_effect=[assessment(80),assessment(30),assessment(45)]))
    result=await routes._plan(None,setup)
    assert len(result.routes)==1
    ors.alternatives.assert_not_called()
    calls=ors.directions.call_args_list
    assert len(calls)==1
    assert all(c.args==(setup.origin,setup.destination) for c in calls)
    assert result.recommended_id is None
    assert any("Hazard-weighted road routing is unavailable" in w for w in result.warnings)


async def test_all_dangerous_not_recommended_and_origin_warning_explained(setup,monkeypatch):
    monkeypatch.setattr(avoid_set,"origin_in_warning",AsyncMock(return_value=True))
    result=await routes._plan(None,setup)
    assert result.recommended_id is None
    assert result.no_lower_risk_route_found
    assert routes.NO_LOWER_EXPOSURE in result.warnings
    assert any("origin is inside" in w for w in result.warnings)
    assert any("information only" in w for w in result.warnings)


async def test_failed_detours_preserve_information_route(setup,monkeypatch):
    monkeypatch.setattr(ors,"directions",AsyncMock(side_effect=[route(distance=135000),ors.ORSNoRoute("no detour"),ors.ORSError("unsupported")]))
    result=await routes._plan(None,setup)
    assert len(result.routes)==1 and result.recommended_id is None


async def test_quota_stops_additional_attempts(setup,monkeypatch):
    monkeypatch.setattr(avoid_set,"build",AsyncMock(return_value=avoid_set.AvoidSet({"type":"MultiPolygon","coordinates":[]},1,[])))
    monkeypatch.setattr(ors,"directions",AsyncMock(side_effect=[route(distance=135000),ors.ORSRateLimited("quota")]))
    result=await routes._plan(None,setup)
    assert ors.directions.await_count==2
    assert result.recommended_id is None


async def test_duplicates_by_geometry_not_rounded_time(setup,monkeypatch):
    monkeypatch.setattr(ors,"alternatives",AsyncMock(return_value=[route(distance=50100,duration=3650),route(.00001)]))
    result=await routes._plan(None,setup)
    # Nearby geometries may lie on opposite sides of a hazard boundary. Only
    # identical geometry is deduplicated before full assessment.
    assert len(result.routes)==2
    assert risk.assess.await_count==2


async def test_excessive_detours_excluded(setup,monkeypatch):
    monkeypatch.setattr(ors,"alternatives",AsyncMock(return_value=[route(.05,150000,9000)]))
    result=await routes._plan(None,setup)
    assert len(result.routes)==1
    assert any("budget" in w for w in result.warnings)


@pytest.mark.parametrize("preference",list(RoutePreference))
async def test_dangerous_is_never_recommended(setup,preference):
    setup.preference=preference
    result=await routes._plan(None,setup)
    assert result.recommended_id is None


async def test_alternative_api_parses_all_features(monkeypatch):
    from app.services.ors import _route_results
    data={"features":[{"geometry":{"type":"LineString","coordinates":r.geometry.coordinates},"properties":{"summary":{"distance":r.distance_m,"duration":r.duration_s}}} for r in [route(),route(.05),route(-.05)]]}
    post=AsyncMock(return_value=data)
    monkeypatch.setattr(ors,"_post",post)
    found=await ors.alternatives(LatLng(lat=29.76,lon=-95.37),LatLng(lat=29.99,lon=-95.34))
    assert len(found)==3
    assert post.call_args.args[1]["alternative_routes"]["target_count"]==3

async def test_long_trip_budget_includes_area_avoidance(setup,monkeypatch):
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=route(distance=135000)))
    monkeypatch.setattr(avoid_set,"build",AsyncMock(return_value=avoid_set.AvoidSet({"type":"MultiPolygon","coordinates":[]},1,[])))
    await routes._plan(None,setup)
    assert ors.directions.await_count==2
    ors.alternatives.assert_not_called()


async def test_over_150km_omits_area_avoidance(setup,monkeypatch):
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=route(distance=160000)))
    await routes._plan(None,setup)
    avoid_set.build.assert_not_awaited()
    ors.alternatives.assert_not_called()


async def test_100km_boundary_does_not_request_provider_alternatives(setup,monkeypatch):
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=route(distance=100000)))
    await routes._plan(None,setup)
    ors.alternatives.assert_not_called()
