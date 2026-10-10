#!/usr/bin/env python
"""Seed a scripted flood scenario into the database.

Demo insurance: if nothing in the US is flooding when you present, this puts the
Houston scenario from app/fixtures.py into TigerData so the real code paths —
PostGIS intersection, scoring, ranking — all run against real data.

Usage:
    python scripts/seed_demo.py                      # seed the Houston scenario
    python scripts/seed_demo.py --at 29.65,-95.28    # recentre it on a location
    python scripts/seed_demo.py --clear              # remove seeded rows

--at is what you want for testing the mobile alert: pass the phone's current
coordinates and the flood zone lands on top of it.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.fixtures import (  # noqa: E402
    FLOOD_POLYGON,
    FLOOD_POLYGON_WEST,
    fixture_gauges,
)

SEED_SOURCE = "demo"


def centroid(ring: list[list[float]]) -> tuple[float, float]:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return sum(lons) / len(lons), sum(lats) / len(lats)


def shift(polygon: list[list[list[float]]], dlon: float, dlat: float) -> list[list[list[float]]]:
    return [[[p[0] + dlon, p[1] + dlat] for p in ring] for ring in polygon]


async def clear(conn: asyncpg.Connection) -> None:
    zones = await conn.execute("DELETE FROM flood_zones WHERE source = $1", SEED_SOURCE)
    readings = await conn.execute(
        "DELETE FROM gauge_readings WHERE site_id IN "
        "(SELECT site_id FROM gauge_sites WHERE site_id LIKE 'demo-%')"
    )
    sites = await conn.execute("DELETE FROM gauge_sites WHERE site_id LIKE 'demo-%'")
    print(f"cleared: {zones}, {readings}, {sites}")


async def seed(conn: asyncpg.Connection, at: tuple[float, float] | None) -> None:
    now = datetime.now(UTC)

    polygons = [FLOOD_POLYGON, FLOOD_POLYGON_WEST]
    if at:
        # Move the whole scenario so the primary zone sits on the given point.
        target_lat, target_lon = at
        base_lon, base_lat = centroid(FLOOD_POLYGON[0])
        dlon, dlat = target_lon - base_lon, target_lat - base_lat
        polygons = [shift(p, dlon, dlat) for p in polygons]
        print(f"recentred scenario on {target_lat},{target_lon}")

    zones = [
        (
            "demo-zone-primary",
            "Flash Flood Warning",
            "severe",
            "DEMO: Flash Flood Warning — rapid rises on Little White Oak Bayou",
            polygons[0],
            now - timedelta(hours=1),
            now + timedelta(hours=6),
        ),
        (
            "demo-zone-secondary",
            "Flood Warning",
            "moderate",
            "DEMO: Flood Warning — Buffalo Bayou out of bank",
            polygons[1],
            now - timedelta(hours=3),
            now + timedelta(hours=9),
        ),
    ]

    for zone_id, event, severity, headline, polygon, effective, expires in zones:
        await conn.execute(
            """
            INSERT INTO flood_zones
                (id, source, event, severity, headline, geom, effective, expires)
            VALUES ($1, $2, $3, $4, $5,
                    ST_Multi(ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($6), 4326))),
                    $7, $8)
            ON CONFLICT (id) DO UPDATE
               SET geom = EXCLUDED.geom,
                   severity = EXCLUDED.severity,
                   headline = EXCLUDED.headline,
                   effective = EXCLUDED.effective,
                   expires = EXCLUDED.expires
            """,
            zone_id,
            SEED_SOURCE,
            event,
            severity,
            headline,
            json.dumps({"type": "Polygon", "coordinates": polygon}),
            effective,
            expires,
        )
    print(f"seeded {len(zones)} flood zone(s)")

    # Gauges, so the gauge component of the score has something to bite on.
    for gauge in fixture_gauges():
        site_id = f"demo-{gauge.site_id}"
        lat, lon = gauge.lat, gauge.lon
        if at:
            lat += at[0] - centroid(FLOOD_POLYGON[0])[1]
            lon += at[1] - centroid(FLOOD_POLYGON[0])[0]

        await conn.execute(
            """
            INSERT INTO gauge_sites
                (site_id, name, geom, flood_stage_ft, action_stage_ft, state_cd)
            VALUES ($1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), $5, $6, 'TX')
            ON CONFLICT (site_id) DO UPDATE
               SET geom = EXCLUDED.geom,
                   flood_stage_ft = EXCLUDED.flood_stage_ft,
                   action_stage_ft = EXCLUDED.action_stage_ft
            """,
            site_id,
            f"DEMO: {gauge.name}",
            lon,
            lat,
            gauge.flood_stage_ft,
            gauge.action_stage_ft,
        )

        await conn.executemany(
            """
            INSERT INTO gauge_readings (time, site_id, gauge_height_ft)
            VALUES ($1, $2, $3)
            ON CONFLICT (site_id, time) DO NOTHING
            """,
            [(r.time, site_id, r.gauge_height_ft) for r in gauge.series],
        )
    print(f"seeded {len(fixture_gauges())} gauge(s) with 24h of readings")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="remove seeded rows and exit")
    parser.add_argument("--at", help="lat,lon to recentre the scenario on")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set — nothing to seed into.", file=sys.stderr)
        return 1

    at = None
    if args.at:
        try:
            lat, lon = (float(v) for v in args.at.split(","))
            at = (lat, lon)
        except ValueError:
            print("--at must look like 29.65,-95.28", file=sys.stderr)
            return 1

    conn = await asyncpg.connect(settings.database_url)
    try:
        if args.clear:
            await clear(conn)
        else:
            await seed(conn, at)
            count = await conn.fetchval(
                "SELECT count(*) FROM flood_zones WHERE expires > now()"
            )
            print(f"active flood zones in database: {count}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
