"""Run against a disposable PostGIS 3.2+ instance using TEST_POSTGIS_URL.

Only connection-local TEMP tables are written. No schema/ingestion/live data
changes. Synthetic lines isolate measurement; they are not routing evidence.
"""
import json
import os

import asyncpg
import pytest

from app.services.risk import _EXPOSURE_SQL

pytestmark=pytest.mark.skipif(not os.environ.get("TEST_POSTGIS_URL"),reason="Disposable TEST_POSTGIS_URL not configured")


@pytest.fixture
async def spatial():
    conn=await asyncpg.connect(os.environ["TEST_POSTGIS_URL"])
    try:
        await conn.execute("CREATE TEMP TABLE flood_zones (source text, severity text, geom geometry(Polygon,4326), expires timestamptz)")
        yield conn
    finally:
        await conn.close()


async def test_screenshot_35_1_miles_not_50_1_with_overlapping_severities(spatial):
    # Equatorial geodesic: longitude degrees map linearly to length.
    degree=111319.49079327358
    mile=1609.344
    length=35.1*mile
    end=length/degree
    await spatial.execute("INSERT INTO flood_zones VALUES ('nws','moderate',ST_MakeEnvelope(-0.001,-0.01,$1,0.01,4326),NULL), ('nws','severe',ST_MakeEnvelope($2,-0.01,$3,0.01,4326),NULL)",end+0.001,10*mile/degree,25*mile/degree)
    line=json.dumps({"type":"LineString","coordinates":[[0,0],[end,0]]})
    naive=await spatial.fetchval("SELECT SUM(ST_Length(ST_Intersection(geom,ST_SetSRID(ST_GeomFromGeoJSON($1),4326))::geography)) FROM flood_zones",line)
    rows=await spatial.fetch(_EXPOSURE_SQL,line)
    unique=sum(r["len_m"] for r in rows)
    assert naive/mile==pytest.approx(50.1,abs=.00001)
    assert unique/mile==pytest.approx(35.1,abs=.00001)
    assert unique<=rows[0]["route_m"]+1e-6
    assert sum(r["len_m"] for r in rows if r["severity"]=="severe")/mile==pytest.approx(15)


async def test_overlapping_equal_severity_union_and_repeated_traversal(spatial):
    await spatial.execute("INSERT INTO flood_zones VALUES ('nws','severe',ST_MakeEnvelope(0,-1,1,1,4326),NULL), ('nws','severe',ST_MakeEnvelope(0.5,-1,1.5,1,4326),NULL)")
    # Travel out and back: each traversal counts, each warning overlap does not.
    rows=await spatial.fetch(_EXPOSURE_SQL,json.dumps({"type":"LineString","coordinates":[[-1,0],[2,0],[-1,0]]}))
    assert sum(r["len_m"] for r in rows)==pytest.approx(rows[0]["route_m"]/2)
    assert {r["edge"] for r in rows}=={1,2}


async def test_hazard_and_warning_distances_are_separate(spatial):
    await spatial.execute("INSERT INTO flood_zones VALUES ('nws','severe',ST_MakeEnvelope(-1,-1,1,1,4326),NULL), ('closure','unknown',ST_MakeEnvelope(-1,-1,1,1,4326),NULL)")
    rows=await spatial.fetch(_EXPOSURE_SQL,json.dumps({"type":"LineString","coordinates":[[-.5,0],[.5,0]]}))
    assert {r["source"] for r in rows}=={"nws","hazard"}
    assert all(r["len_m"]==pytest.approx(r["route_m"]) for r in rows)


async def test_expired_and_outside_warnings_do_not_count(spatial):
    await spatial.execute("INSERT INTO flood_zones VALUES ('nws','severe',ST_MakeEnvelope(-1,-1,1,1,4326),now()-interval '1 minute'), ('nws','severe',ST_MakeEnvelope(5,5,6,6,4326),NULL)")
    assert not await spatial.fetch(_EXPOSURE_SQL,json.dumps({"type":"LineString","coordinates":[[-.5,0],[.5,0]]}))
