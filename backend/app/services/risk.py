"""The risk engine — Orion's actual product.

ORS proposes routes; this module disposes of them. Every candidate geometry is
re-checked against live flood polygons in PostGIS, because ORS avoid_polygons
cannot be trusted to have worked.

Score is 0 (safest) to 100 (worst), built from four weighted components:

    flood_exposure   0-50   route length inside active flood polygons
    low_lying        0-25   depth/extent of terrain dips along the route
    gauge_proximity  0-20   nearby river gauges at or above flood stage
    approach_margin  0-5    how close the route passes to a flood edge

The DB-touching part is `assess`; the maths is in `score`, which is pure so it
can be unit-tested with plain fixtures.
"""

import json
import logging
from dataclasses import dataclass, field

import asyncpg

from ..config import get_settings
from ..models import (
    FlaggedSegment,
    FloodSeverity,
    LineString,
    RiskBand,
    RiskBreakdown,
)

log = logging.getLogger(__name__)

# How much each severity multiplies measured exposure length.
SEVERITY_WEIGHT: dict[FloodSeverity, float] = {
    FloodSeverity.EXTREME: 1.0,
    FloodSeverity.SEVERE: 0.9,
    FloodSeverity.MODERATE: 0.7,
    FloodSeverity.MINOR: 0.5,
    FloodSeverity.UNKNOWN: 0.6,
}

# Weighted exposure (metres) at which the flood component saturates.
EXPOSURE_SATURATION_M = 2_000.0
# Any contact with floodwater at all scores at least this much, because
# "briefly submerged" is still impassable.
EXPOSURE_FLOOR = 20.0

# Terrain dip tuning.
DIP_THRESHOLD_M = 3.0
DIP_SATURATION_M = 12.0
DIP_EXTENT_SATURATION = 0.30

# Band thresholds.
BAND_DANGEROUS = 50.0
BAND_CAUTION = 20.0

# Distance at which passing near a flood edge stops mattering.
APPROACH_SATURATION_M = 1_000.0


@dataclass
class ExposureHit:
    """One stretch of route inside one flood zone."""

    zone_id: str
    event: str
    severity: FloodSeverity
    length_m: float
    geometry: LineString | None = None


@dataclass
class GaugeInfluence:
    site_id: str
    name: str
    distance_m: float
    at_flood_stage: bool
    at_action_stage: bool


@dataclass
class Assessment:
    breakdown: RiskBreakdown
    band: RiskBand
    flagged_segments: list[FlaggedSegment] = field(default_factory=list)
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    warnings: list[str] = field(default_factory=list)
    clear_of_flooding: bool = True


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))



# --------------------------------------------------------------------------- #
# Pure scoring
# --------------------------------------------------------------------------- #


def flood_exposure_score(hits: list[ExposureHit]) -> float:
    weighted = sum(h.length_m * SEVERITY_WEIGHT.get(h.severity, 0.6) for h in hits)
    if weighted <= 0:
        return 0.0
    return max(EXPOSURE_FLOOR, 50.0 * _clamp(weighted / EXPOSURE_SATURATION_M))


def basin_depths(elevations: list[float]) -> list[float]:
    """How deep each point sits inside a basin, in metres.

    Water pools at a point only when there is higher ground on *both* sides of
    it, so the enclosing height is min(highest ground before, highest ground
    after) — the standard trapped-water computation. A point on a steady slope
    has higher ground on one side only and therefore zero depth, which is what
    separates a real bayou bottom from an ordinary hill climb.

    Comparing against a route-wide percentile instead would score the entire
    lower half of any long descent as a flood risk.
    """
    n = len(elevations)
    if n < 3:
        return [0.0] * n

    prefix_max = [0.0] * n  # highest ground strictly before i
    running = float("-inf")
    for i in range(n):
        prefix_max[i] = running
        running = max(running, elevations[i])

    suffix_max = [0.0] * n  # highest ground strictly after i
    running = float("-inf")
    for i in range(n - 1, -1, -1):
        suffix_max[i] = running
        running = max(running, elevations[i])

    depths = []
    for i, elev in enumerate(elevations):
        enclosing = min(prefix_max[i], suffix_max[i])
        depths.append(max(0.0, enclosing - elev) if enclosing != float("-inf") else 0.0)
    return depths


def low_lying_score(elevations: list[float]) -> float:
    """Score the basins along a route.

    Absolute elevation says little — 2 m above sea level is unremarkable in
    Florida and alarming in Denver. What matters is a stretch of road sitting
    below the ground that surrounds it, because that is where water collects.
    """
    if len(elevations) < 4:
        return 0.0

    depths = basin_depths(elevations)
    deep = [d for d in depths if d > DIP_THRESHOLD_M]
    if not deep:
        return 0.0

    dip_severity = _clamp(max(depths) / DIP_SATURATION_M)
    dip_extent = _clamp((len(deep) / len(elevations)) / DIP_EXTENT_SATURATION)
    return 25.0 * (0.6 * dip_severity + 0.4 * dip_extent)


def gauge_proximity_score(gauges: list[GaugeInfluence]) -> float:
    settings = get_settings()
    influence = settings.gauge_influence_m

    contributions: list[float] = []
    for g in gauges:
        if g.at_flood_stage:
            stage_factor = 1.0
        elif g.at_action_stage:
            stage_factor = 0.5
        else:
            continue
        distance_factor = _clamp(1.0 - (g.distance_m / influence))
        contributions.append(stage_factor * distance_factor)

    if not contributions:
        return 0.0

    contributions.sort(reverse=True)
    # Worst gauge dominates; the rest add a little, so a route past five flooded
    # gauges scores worse than a route past one.
    raw = contributions[0] + 0.3 * sum(contributions[1:])
    return 20.0 * _clamp(raw)


def approach_margin_score(nearest_zone_m: float | None) -> float:
    if nearest_zone_m is None:
        return 0.0
    return 5.0 * _clamp(1.0 - (nearest_zone_m / APPROACH_SATURATION_M))


def band_for(total: float, has_exposure: bool) -> RiskBand:
    if has_exposure:
        # Driving through floodwater is categorically unsafe, whatever the
        # arithmetic says.
        return RiskBand.DANGEROUS
    if total >= BAND_DANGEROUS:
        return RiskBand.DANGEROUS
    if total >= BAND_CAUTION:
        return RiskBand.CAUTION
    return RiskBand.SAFE


def score(
    hits: list[ExposureHit],
    elevations: list[float],
    gauges: list[GaugeInfluence],
    nearest_zone_m: float | None,
) -> tuple[RiskBreakdown, RiskBand]:
    """Pure core. No I/O — unit-test this directly."""
    exposure = flood_exposure_score(hits)
    low_lying = low_lying_score(elevations)
    gauge = gauge_proximity_score(gauges)
    approach = approach_margin_score(nearest_zone_m)

    total = _clamp(exposure + low_lying + gauge + approach, 0.0, 100.0)
    breakdown = RiskBreakdown(
        flood_exposure=round(exposure, 2),
        low_lying=round(low_lying, 2),
        gauge_proximity=round(gauge, 2),
        approach_margin=round(approach, 2),
        total=round(total, 2),
    )
    return breakdown, band_for(total, bool(hits))


# --------------------------------------------------------------------------- #
# Database-backed assessment
# --------------------------------------------------------------------------- #

_EXPOSURE_SQL = """
WITH route AS (
    SELECT ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)) AS geom
),
zones AS (
    SELECT id, event, severity, geom
    FROM flood_zones
    WHERE expires IS NULL OR expires > now()
),
hits AS (
    SELECT z.id, z.event, z.severity, ST_Intersection(r.geom, z.geom) AS geom
    FROM route r
    JOIN zones z ON ST_Intersects(r.geom, z.geom)
)
SELECT h.id, h.event, h.severity,
       ST_AsGeoJSON(d.geom)            AS seg,
       ST_Length(d.geom::geography)    AS len_m
FROM hits h,
     LATERAL ST_Dump(h.geom) d
WHERE ST_GeometryType(d.geom) = 'ST_LineString'
  AND ST_Length(d.geom::geography) > 1
"""

_NEAREST_SQL = """
SELECT MIN(ST_Distance(
           ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326))::geography,
           geom::geography
       ))
FROM flood_zones
WHERE expires IS NULL OR expires > now()
"""

_GAUGE_SQL = """
WITH route AS (
    SELECT ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)) AS geom
)
SELECT g.site_id,
       g.name,
       ST_Distance(r.geom::geography, g.geom::geography) AS distance_m,
       latest.gauge_height_ft,
       g.flood_stage_ft,
       g.action_stage_ft
FROM gauge_sites g
CROSS JOIN route r
JOIN LATERAL (
    SELECT gauge_height_ft
    FROM gauge_readings
    WHERE site_id = g.site_id
      AND gauge_height_ft IS NOT NULL
    ORDER BY time DESC
    LIMIT 1
) latest ON TRUE
WHERE ST_DWithin(r.geom::geography, g.geom::geography, $2)
"""


def elevations_of(geometry: LineString) -> list[float]:
    return [c[2] for c in geometry.coordinates if len(c) > 2]


async def assess(conn: asyncpg.Connection, geometry: LineString) -> Assessment:
    """Score one candidate route against live conditions."""
    settings = get_settings()
    geojson = json.dumps({"type": "LineString", "coordinates": geometry.coordinates})
    warnings: list[str] = []

    # --- flood exposure: the authoritative avoidance check ------------------ #
    hits: list[ExposureHit] = []
    segments: list[FlaggedSegment] = []
    for row in await conn.fetch(_EXPOSURE_SQL, geojson):
        severity = _severity(row["severity"])
        hits.append(
            ExposureHit(
                zone_id=row["id"],
                event=row["event"],
                severity=severity,
                length_m=float(row["len_m"]),
            )
        )
        segments.append(
            FlaggedSegment(
                geometry=LineString(coordinates=json.loads(row["seg"])["coordinates"]),
                length_m=round(float(row["len_m"]), 1),
                flood_zone_id=row["id"],
                event=row["event"],
                severity=severity,
            )
        )

    nearest = await conn.fetchval(_NEAREST_SQL, geojson)
    nearest_m = float(nearest) if nearest is not None else None

    gauges: list[GaugeInfluence] = []
    for row in await conn.fetch(_GAUGE_SQL, geojson, settings.gauge_influence_m):
        height = row["gauge_height_ft"]
        flood_stage = row["flood_stage_ft"]
        action_stage = row["action_stage_ft"]
        gauges.append(
            GaugeInfluence(
                site_id=row["site_id"],
                name=row["name"],
                distance_m=float(row["distance_m"]),
                at_flood_stage=bool(
                    height is not None and flood_stage is not None and height >= flood_stage
                ),
                at_action_stage=bool(
                    height is not None and action_stage is not None and height >= action_stage
                ),
            )
        )

    elevations = elevations_of(geometry)
    if not elevations:
        warnings.append("No elevation data for this route; terrain risk not assessed.")

    breakdown, band = score(hits, elevations, gauges, nearest_m)

    if hits:
        total_m = sum(h.length_m for h in hits)
        events = sorted({h.event for h in hits})
        warnings.append(
            f"Crosses {', '.join(events)} for {total_m / 1000:.1f} km — do not drive this."
        )
    flooded_gauges = [g for g in gauges if g.at_flood_stage]
    if flooded_gauges:
        warnings.append(
            f"{len(flooded_gauges)} river gauge(s) at or above flood stage within "
            f"{settings.gauge_influence_m / 1000:.0f} km of this route."
        )

    return Assessment(
        breakdown=breakdown,
        band=band,
        flagged_segments=segments,
        min_elevation_m=min(elevations) if elevations else None,
        max_elevation_m=max(elevations) if elevations else None,
        warnings=warnings,
        clear_of_flooding=not hits,
    )


def _severity(value: str | None) -> FloodSeverity:
    if not value:
        return FloodSeverity.UNKNOWN
    try:
        return FloodSeverity(value.lower())
    except ValueError:
        return FloodSeverity.UNKNOWN
