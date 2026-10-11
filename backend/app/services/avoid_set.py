"""Build ORS-legal avoid polygons out of live flood zones.

The public ORS instance enforces hard limits (200 km2 per polygon, 20 km extent,
150 km route length when avoidance is used) and is known to silently drop
polygons past the first few. So we send as little geometry as possible:

    clip to the request corridor -> buffer -> union -> simplify -> top N parts

Whatever comes back from ORS is still verified independently in risk.py.
"""

import json
import logging
import math
from typing import Any

import asyncpg

from ..config import get_settings
from ..models import FloodSeverity, LatLng

log = logging.getLogger(__name__)

# Only these severities go into the "balanced" candidate's avoid set.
HIGH_SEVERITIES = ("extreme", "severe")

_AVOID_SQL = """
WITH corridor AS (
    SELECT ST_Buffer(
               ST_MakeLine(
                   ST_SetSRID(ST_MakePoint($1, $2), 4326),
                   ST_SetSRID(ST_MakePoint($3, $4), 4326)
               )::geography,
               $5
           )::geometry AS geom
),
relevant AS (
    SELECT fz.id,
           fz.severity,
           ST_Intersection(fz.geom, c.geom) AS geom
    FROM flood_zones fz
    CROSS JOIN corridor c
    WHERE (fz.expires IS NULL OR fz.expires > now())
      AND fz.source <> 'nws'
      AND ($7::text[] IS NULL OR fz.severity = ANY($7::text[]))
      AND ST_Intersects(fz.geom, c.geom)
),
buffered AS (
    SELECT ST_Buffer(geom::geography, $6)::geometry AS geom
    FROM relevant
    WHERE NOT ST_IsEmpty(geom)
),
merged AS (
    SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM buffered
),
simplified AS (
    -- ~30 m tolerance: enough to cut vertex count hard without moving edges
    -- meaningfully, since we already buffered outward by flood_buffer_m.
    SELECT ST_SimplifyPreserveTopology(geom, 0.0003) AS geom FROM merged
),
parts AS (
    SELECT (ST_Dump(geom)).geom AS geom FROM simplified
)
SELECT ST_AsGeoJSON(geom)                AS gj,
       ST_Area(geom::geography) / 1e6    AS area_km2,
       GREATEST(
           ST_Distance(
               ST_SetSRID(ST_MakePoint(ST_XMin(geom), ST_YMin(geom)), 4326)::geography,
               ST_SetSRID(ST_MakePoint(ST_XMax(geom), ST_YMin(geom)), 4326)::geography
           ),
           ST_Distance(
               ST_SetSRID(ST_MakePoint(ST_XMin(geom), ST_YMin(geom)), 4326)::geography,
               ST_SetSRID(ST_MakePoint(ST_XMin(geom), ST_YMax(geom)), 4326)::geography
           )
       ) / 1000.0                        AS extent_km
FROM parts
WHERE ST_GeometryType(geom) = 'ST_Polygon'
  AND NOT ST_IsEmpty(geom)
ORDER BY area_km2 DESC
"""


def _extent_km(polygons: list) -> float:
    points = [point for polygon in polygons for ring in polygon for point in ring]
    if not points:
        return 0.0
    # Bounding diagonal is conservative for the provider's extent constraint.
    lon1, lon2 = min(p[0] for p in points), max(p[0] for p in points)
    lat1, lat2 = min(p[1] for p in points), max(p[1] for p in points)
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


class AvoidSet:
    def __init__(
        self,
        geojson: dict[str, Any] | None,
        zone_count: int,
        warnings: list[str],
    ):
        self.geojson = geojson
        self.zone_count = zone_count
        self.warnings = warnings

    def __bool__(self) -> bool:
        return self.geojson is not None


async def count_active_zones(conn: asyncpg.Connection) -> int:
    return int(
        await conn.fetchval(
            "SELECT count(*) FROM flood_zones WHERE expires IS NULL OR expires > now()"
        )
        or 0
    )


async def build(
    conn: asyncpg.Connection,
    origin: LatLng,
    destination: LatLng,
    high_severity_only: bool = False,
) -> AvoidSet:
    """Assemble the avoid-polygon payload for one ORS call."""
    settings = get_settings()
    warnings: list[str] = []

    severities = list(HIGH_SEVERITIES) if high_severity_only else None

    rows = await conn.fetch(
        _AVOID_SQL,
        origin.lon,
        origin.lat,
        destination.lon,
        destination.lat,
        settings.corridor_buffer_m,
        settings.flood_buffer_m,
        severities,
    )

    if not rows:
        return AvoidSet(None, 0, warnings)

    kept: list[list[list[list[float]]]] = []
    dropped_oversize = 0
    total_area = 0.0

    for row in rows:
        if len(kept) >= settings.max_avoid_polygon_parts:
            break

        if (
            total_area + row["area_km2"] > settings.max_avoid_polygon_area_km2
            or row["extent_km"] > settings.max_avoid_polygon_extent_km
        ):
            # ORS would reject the whole request. Dropping the part is safer:
            # risk.py still detects and down-ranks any route crossing it.
            dropped_oversize += 1
            log.info(
                "dropped oversize avoid polygon (%.1f km2, %.1f km extent)",
                row["area_km2"],
                row["extent_km"],
            )
            continue

        polygon = json.loads(row["gj"])
        if _extent_km(kept + [polygon["coordinates"]]) > settings.max_avoid_polygon_extent_km:
            dropped_oversize += 1
            continue
        kept.append(polygon["coordinates"])
        total_area += row["area_km2"]

    if dropped_oversize:
        warnings.append(
            f"{dropped_oversize} flood zone(s) exceed the routing service's "
            f"{settings.max_avoid_polygon_area_km2:g} km2 total / "
            f"{settings.max_avoid_polygon_extent_km:g} km avoidance limit and were omitted. "
            "Routes crossing them are still flagged."
        )

    if len(rows) - len(kept) > dropped_oversize:
        warnings.append(
            f"Only {len(kept)} eligible hazard polygon(s) were "
            "sent to the routing service; all zones were still used for scoring."
        )

    if not kept:
        return AvoidSet(None, len(rows), warnings)

    return AvoidSet(
        {"type": "MultiPolygon", "coordinates": kept},
        len(rows),
        warnings,
    )


def severity_from_text(value: str | None) -> FloodSeverity:
    if not value:
        return FloodSeverity.UNKNOWN
    try:
        return FloodSeverity(value.lower())
    except ValueError:
        return FloodSeverity.UNKNOWN


async def origin_in_warning(conn: asyncpg.Connection, origin: LatLng) -> bool:
    return bool(await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM flood_zones WHERE source = 'nws' "
        "AND (expires IS NULL OR expires > now()) "
        "AND ST_Covers(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)))",
        origin.lon, origin.lat,
    ))
