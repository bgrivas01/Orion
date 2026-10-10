"""Build ORS-legal avoid polygons out of live flood zones.

The public ORS instance enforces hard limits (200 km2 per polygon, 20 km extent,
150 km route length when avoidance is used) and is known to silently drop
polygons past the first few. So we send as little geometry as possible:

    clip to the request corridor -> buffer -> union -> simplify -> top N parts

Whatever comes back from ORS is still verified independently in risk.py.
"""

import json
import logging
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

    for row in rows:
        if len(kept) >= settings.max_avoid_polygon_parts:
            break

        if (
            row["area_km2"] > settings.max_avoid_polygon_area_km2
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
        kept.append(polygon["coordinates"])

    if dropped_oversize:
        warnings.append(
            f"{dropped_oversize} flood zone(s) exceed the routing service's "
            "200 km2 / 20 km avoidance limit and could not be routed around. "
            "Routes crossing them are still flagged."
        )

    if len(rows) > settings.max_avoid_polygon_parts:
        warnings.append(
            f"Only the {settings.max_avoid_polygon_parts} largest flood zones were "
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
