"""Routing failures and broad alerts never produce invented routes."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.models import LatLng, LineString, RouteRequest, FloodSeverity, RiskBand
from app.routers import routes
from app.services import ors, avoid_set, risk


@pytest.mark.parametrize("code,error", [(2010, ors.ORSLocationError), (2009, ors.ORSNoRoute)])
async def test_provider_404_code_and_sanitized_log(monkeypatch, caplog, code, error):
    secret = "test-key-do-not-log"
    settings = Settings(_env_file=None, ors_api_key=secret)
    monkeypatch.setattr(ors, "get_settings", lambda: settings)
    real_client = httpx.AsyncClient
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(404, json={"error": {"code": code, "message": secret}})
    monkeypatch.setattr(ors.httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(handle), **kw))
    with caplog.at_level(logging.INFO), pytest.raises(error) as result:
        await ors.directions(LatLng(lat=30.23,lon=-93.38), LatLng(lat=30.21,lon=-93.14))
    assert str(code) in str(result.value)
    assert secret not in caplog.text + str(result.value)
    assert f"code={code}" in caplog.text
    assert "avoidance=False" in caplog.text
    assert len(requests) == 1
    assert "options" not in json.loads(requests[0].content)


def test_generic_404_is_not_assumed_to_be_off_network():
    with pytest.raises(ors.ORSError, match="unclassified upstream 404") as result:
        ors.response_data(httpx.Response(404, text="private response"), "routing")
    assert not isinstance(result.value, (ors.ORSLocationError, ors.ORSNoRoute))


@pytest.mark.parametrize("failure", [ors.ORSLocationError("2010: choose entrance"), ors.ORSNoRoute("2009: no route")])
async def test_fastest_already_has_no_avoidance_and_is_not_retried(monkeypatch, failure):
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(routes.avoid_set_svc, "count_active_zones", AsyncMock(return_value=1))
    monkeypatch.setattr(routes.avoid_set_svc, "build", AsyncMock(return_value=avoid_set.AvoidSet(None,1,["Oversize area omitted"])))
    call = AsyncMock(side_effect=failure)
    monkeypatch.setattr(ors, "directions", call)
    with pytest.raises(HTTPException) as result:
        await routes._plan(None, RouteRequest(origin=LatLng(lat=30.23,lon=-93.38),destination=LatLng(lat=30.21,lon=-93.14)))
    assert result.value.status_code == 422
    assert str(failure) in result.value.detail
    call.assert_awaited_once()
    assert call.call_args.kwargs["avoid_polygons"] is None


async def test_no_key_does_not_fabricate_houston_route(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None, ors_api_key="",use_fixtures=False))
    with pytest.raises(HTTPException) as result:
        await routes.plan_routes(RouteRequest(origin=LatLng(lat=30.23,lon=-93.38),destination=LatLng(lat=30.21,lon=-93.14)))
    assert result.value.status_code == 503


def polygon(x=0):
    return {"type":"Polygon","coordinates":[[[x,0],[x+.01,0],[x+.01,.01],[x,.01],[x,0]]]}


async def test_avoidance_total_area_is_capped(monkeypatch):
    monkeypatch.setattr(avoid_set,"get_settings",lambda: Settings(_env_file=None))
    conn=SimpleNamespace(fetch=AsyncMock(return_value=[
        {"gj":json.dumps(polygon()),"area_km2":120,"extent_km":12},
        {"gj":json.dumps(polygon(.02)),"area_km2":100,"extent_km":10}]))
    result=await avoid_set.build(conn,LatLng(lat=0,lon=0),LatLng(lat=0,lon=.1))
    assert len(result.geojson["coordinates"])==1
    assert result.warnings
    assert "fz.source <> 'nws'" in conn.fetch.call_args.args[0]


async def test_separated_parts_cannot_exceed_combined_extent(monkeypatch):
    monkeypatch.setattr(avoid_set,"get_settings",lambda: Settings(_env_file=None))
    conn=SimpleNamespace(fetch=AsyncMock(return_value=[
        {"gj":json.dumps(polygon(x)),"area_km2":1,"extent_km":1} for x in [0,1]]))
    result=await avoid_set.build(conn,LatLng(lat=0,lon=0),LatLng(lat=0,lon=1))
    assert len(result.geojson["coordinates"])==1


async def test_nws_overlap_is_reported_as_warning_not_confirmed_water(monkeypatch):
    monkeypatch.setattr(risk,"get_settings",lambda: Settings(_env_file=None))
    conn=SimpleNamespace(fetch=AsyncMock(side_effect=[[
        {"id":"nws-alert","source":"nws","event":"Flood Warning","severity":"minor",
         "len_m":10,"seg":json.dumps({"coordinates":[[-95,29],[-95,29.01]]})}],[]]),
        fetchval=AsyncMock(return_value=0))
    result=await risk.assess(conn,LineString(coordinates=[[-95,29,10],[-95,29.01,10]]))
    assert result.band != RiskBand.DANGEROUS
    assert any("not confirmed flooded roads" in w for w in result.warnings)
    assert not any("do not drive this" in w for w in result.warnings)
    assert result.flagged_segments  # Alert exposure is not discarded.


async def test_houston_success_still_returns_provider_geometry(monkeypatch):
    from app.models import RiskBreakdown
    monkeypatch.setattr(routes,"get_settings",lambda: Settings(_env_file=None))
    monkeypatch.setattr(avoid_set,"count_active_zones",AsyncMock(return_value=0))
    geometry=LineString(coordinates=[[-95.3698,29.7604,10],[-95.3698,29.7634,10]])
    monkeypatch.setattr(ors,"directions",AsyncMock(return_value=ors.RouteResult(geometry,350,60)))
    monkeypatch.setattr(risk,"assess",AsyncMock(return_value=risk.Assessment(
        breakdown=RiskBreakdown(flood_exposure=0,low_lying=0,gauge_proximity=0,approach_margin=0,total=0),
        band=RiskBand.SAFE,flagged_segments=[])))
    monkeypatch.setattr(routes,"_persist",AsyncMock())
    result=await routes._plan(None,RouteRequest(origin=LatLng(lat=29.7604,lon=-95.3698),destination=LatLng(lat=29.7634,lon=-95.3698)))
    assert len(result.routes)==1
    assert result.routes[0].geometry==geometry


@pytest.fixture(autouse=True)
def isolate_candidate_search(monkeypatch):
    monkeypatch.setattr(ors, "alternatives", AsyncMock(return_value=[]))
    monkeypatch.setattr(avoid_set, "origin_in_warning", AsyncMock(return_value=False))
