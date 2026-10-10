"""Integration tests for the PostGIS layer.

These need a real database with PostGIS (Tiger Cloud, or any Postgres with the
extension) and are skipped without one:

    DATABASE_URL='postgres://...' .venv/bin/python -m pytest tests/test_postgis.py -v

This is where the project's central claim gets proven: a route through a flood
polygon must be detected as exposed, and a route around it must come back clean.
ORS is not involved — the geometries are synthetic, so the test isolates our own
verification logic.
"""

import json
import os

import asyncpg
import pytest

from app.config import get_settings
from app.models import LatLng, LineString
from app.services import avoid_set, risk

DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL not set; PostGIS integration tests skipped"
)

# A square flood zone sitting astride the direct west-east line at y=0.
FLOOD_SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-0.01, -0.01], [0.01, -0.01], [0.01, 0.01], [-0.01, 0.01], [-0.01, -0.01]]],
}

# Straight through the middle of it.
THROUGH = LineString(coordinates=[[-0.05, 0.0, 12.0], [0.0, 0.0, 4.0], [0.05, 0.0, 12.0]])
# Detours well to the north of it.
AROUND = LineString(
    coordinates=[[-0.05, 0.0, 12.0], [-0.02, 0.05, 14.0], [0.02, 0.05, 14.0], [0.05, 0.0, 12.0]]
)


@pytest.fixture
async def conn():
    connection = await asyncpg.connect(DATABASE_URL)

    # Apply the schema, then work inside a transaction we always roll back so
    # the developer's database is left exactly as it was.
    for path in ("sql/001_init.sql",):
        with open(path) as fh:
            await connection.execute(fh.read())

    tx = connection.transaction()
    await tx.start()
    try:
        await connection.execute(
            """
            INSERT INTO flood_zones (id, source, event, severity, headline, geom, expires)
            VALUES ('test-zone', 'test', 'Flash Flood Warning', 'severe', 'test fixture',
                    ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)),
                    now() + INTERVAL '6 hours')
            """,
            json.dumps(FLOOD_SQUARE),
        )
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def test_extensions_present(conn):
    names = {
        r["extname"]
        for r in await conn.fetch(
            "SELECT extname FROM pg_extension WHERE extname = ANY($1::text[])",
            ["postgis", "timescaledb"],
        )
    }
    assert "postgis" in names, "PostGIS is required"
    assert "timescaledb" in names, "TimescaleDB is required for the gauge hypertable"


async def test_gauge_readings_is_a_hypertable(conn):
    count = await conn.fetchval(
        "SELECT count(*) FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = 'gauge_readings'"
    )
    assert count == 1


async def test_route_through_flooding_is_detected(conn):
    """The headline guarantee."""
    result = await risk.assess(conn, THROUGH)

    assert result.clear_of_flooding is False
    assert result.flagged_segments, "expected a flagged segment across the flood zone"
    assert result.breakdown.flood_exposure > 0
    assert result.band.value == "dangerous"

    # The flagged length should be about the 0.02-degree width of the square.
    flagged = sum(s.length_m for s in result.flagged_segments)
    assert 1_500 < flagged < 3_500, f"unexpected flagged length {flagged:.0f} m"


async def test_route_around_flooding_is_clean(conn):
    result = await risk.assess(conn, AROUND)

    assert result.clear_of_flooding is True
    assert result.flagged_segments == []
    assert result.breakdown.flood_exposure == 0.0
    assert result.band.value in ("safe", "caution")


async def test_detour_scores_better_than_the_direct_route(conn):
    """What the product actually promises: the clear route ranks first."""
    through = await risk.assess(conn, THROUGH)
    around = await risk.assess(conn, AROUND)
    assert around.breakdown.total < through.breakdown.total


async def test_avoid_set_is_built_from_live_zones(conn):
    result = await avoid_set.build(conn, LatLng(lat=0.0, lon=-0.05), LatLng(lat=0.0, lon=0.05))

    assert result.geojson is not None, "expected an avoid polygon for a corridor crossing the zone"
    assert result.geojson["type"] == "MultiPolygon"
    assert result.zone_count == 1


async def test_avoid_set_respects_ors_limits(conn):
    """Every part we send must be inside ORS's 200 km2 / 20 km caps."""
    settings = get_settings()
    result = await avoid_set.build(conn, LatLng(lat=0.0, lon=-0.05), LatLng(lat=0.0, lon=0.05))
    assert result.geojson is not None

    for coordinates in result.geojson["coordinates"]:
        row = await conn.fetchrow(
            """
            WITH g AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326) AS geom)
            SELECT ST_Area(geom::geography) / 1e6 AS area_km2,
                   GREATEST(
                       ST_Distance(
                           ST_SetSRID(ST_MakePoint(ST_XMin(geom), ST_YMin(geom)), 4326)::geography,
                           ST_SetSRID(ST_MakePoint(ST_XMax(geom), ST_YMin(geom)), 4326)::geography),
                       ST_Distance(
                           ST_SetSRID(ST_MakePoint(ST_XMin(geom), ST_YMin(geom)), 4326)::geography,
                           ST_SetSRID(ST_MakePoint(ST_XMin(geom), ST_YMax(geom)), 4326)::geography)
                   ) / 1000.0 AS extent_km
            FROM g
            """,
            json.dumps({"type": "Polygon", "coordinates": coordinates}),
        )
        assert row["area_km2"] <= settings.max_avoid_polygon_area_km2
        assert row["extent_km"] <= settings.max_avoid_polygon_extent_km

    assert len(result.geojson["coordinates"]) <= settings.max_avoid_polygon_parts


async def test_avoid_set_ignores_zones_outside_the_corridor(conn):
    """A flood zone on the other side of the state must not shrink the route."""
    result = await avoid_set.build(
        conn, LatLng(lat=40.0, lon=-100.0), LatLng(lat=40.1, lon=-100.1)
    )
    assert result.geojson is None


async def test_expired_zones_are_ignored(conn):
    await conn.execute("UPDATE flood_zones SET expires = now() - INTERVAL '1 hour'")
    result = await risk.assess(conn, THROUGH)
    assert result.clear_of_flooding is True


async def test_alert_check_sql_runs(conn):
    """Exercise the mobile polling query against real geometry."""
    rows = await conn.fetch(
        """
        SELECT id, ST_Contains(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)) AS inside
        FROM flood_zones
        WHERE (expires IS NULL OR expires > now())
          AND ST_DWithin(ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                         geom::geography, $3)
        """,
        0.0,
        0.0,
        5000,
    )
    assert len(rows) == 1
    assert rows[0]["inside"] is True
