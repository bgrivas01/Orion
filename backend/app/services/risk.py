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
    source: str = "unknown"


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
    route_length_m: float = 0
    warning_exposure_m: float = 0
    warning_exposure_percent: float = 0
    warning_severity_m: dict[str, float] = field(default_factory=dict)
    hazard_exposure_m: float = 0
    initial_warning_exit_m: float = 0
    warning_reentries: int = 0
    warning_intersection: bool = False
    hazard_intersection: bool = False


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))



# --------------------------------------------------------------------------- #
# Pure scoring
# --------------------------------------------------------------------------- #


def flood_exposure_score(hits: list[ExposureHit]) -> float:
    weighted = sum(h.length_m * SEVERITY_WEIGHT.get(h.severity, 0.6) for h in hits)
    if weighted <= 0:
        return 0.0
    if any(h.source != "nws" for h in hits):
        return max(EXPOSURE_FLOOR, 50.0 * _clamp(weighted / EXPOSURE_SATURATION_M))
    # Smooth display score; exact severity distances, not this compressed score,
    # drive Safest ranking. No 2-km plateau for precautionary warnings.
    return 50.0 * weighted / (weighted + 10_000.0)


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

    total = _clamp(sum(round(v,2) for v in (exposure,low_lying,gauge,approach)), 0.0, 100.0)
    breakdown = RiskBreakdown(
        flood_exposure=round(exposure, 2),
        low_lying=round(low_lying, 2),
        gauge_proximity=round(gauge, 2),
        approach_margin=round(approach, 2),
        total=round(total, 2),
    )
    return breakdown, band_for(total, any(h.source != "nws" for h in hits))


# --------------------------------------------------------------------------- #
# Database-backed assessment
# --------------------------------------------------------------------------- #

_EXPOSURE_SQL = """
WITH route AS (
 SELECT ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($1),4326)) geom
), raw_edges AS (
 SELECT d.path[1] edge, d.geom, ST_Length(d.geom::geography) edge_m
 FROM route, LATERAL ST_DumpSegments(route.geom) d
 WHERE ST_Length(d.geom)>0
), edges AS (
 SELECT *, COALESCE(SUM(edge_m) OVER (ORDER BY edge ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) start_m
 FROM raw_edges
), zones AS (
 SELECT CASE WHEN source='nws' THEN 'nws' ELSE 'hazard' END source,
        CASE WHEN severity IN ('extreme','severe','moderate','minor') THEN severity ELSE 'unknown' END severity,
        CASE severity WHEN 'extreme' THEN 5 WHEN 'severe' THEN 4
             WHEN 'moderate' THEN 3 WHEN 'minor' THEN 1 ELSE 2 END rank,
        ST_MakeValid(geom) geom
 FROM flood_zones
 WHERE (expires IS NULL OR expires > now())
 AND ST_Intersects(geom,(SELECT geom FROM route))
), dissolved AS (
 SELECT source,severity,rank,ST_UnaryUnion(ST_Collect(geom)) geom
 FROM zones GROUP BY source,severity,rank
), exclusive AS (
 SELECT z.source,z.severity,z.rank,
 ST_Difference(z.geom,COALESCE((SELECT ST_UnaryUnion(ST_Collect(h.geom))
 FROM dissolved h WHERE h.source=z.source AND h.rank>z.rank),
 ST_GeomFromText('POLYGON EMPTY',4326))) geom FROM dissolved z
), pieces AS (
 SELECT e.edge,e.geom edge_geom,e.edge_m,e.start_m,z.source,z.severity,
        (ST_Dump(ST_CollectionExtract(ST_Intersection(e.geom,z.geom),2))).geom geom
 FROM edges e JOIN exclusive z ON ST_Intersects(e.geom,z.geom)
), measured AS (
 SELECT *, LEAST(ST_LineLocatePoint(edge_geom,ST_StartPoint(geom)),
                 ST_LineLocatePoint(edge_geom,ST_EndPoint(geom))) lo,
           GREATEST(ST_LineLocatePoint(edge_geom,ST_StartPoint(geom)),
                    ST_LineLocatePoint(edge_geom,ST_EndPoint(geom))) hi
 FROM pieces
)
SELECT source || ':' || severity id,source,severity,
       CASE WHEN source='nws' THEN 'NWS warning area' ELSE 'Hazard area' END event,
       ST_AsGeoJSON(geom) seg,(hi-lo)*edge_m len_m,edge,lo,hi,edge_m,start_m,
       (SELECT SUM(edge_m) FROM edges) route_m
FROM measured WHERE hi>lo
ORDER BY edge,lo
"""

_NEAREST_SQL = """
WITH route AS (SELECT ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($1),4326)) geom)
SELECT json_build_object(
 'nearest', MIN(ST_Distance(route.geom::geography,flood_zones.geom::geography)),
 'warning_intersection', COALESCE(bool_or(source='nws' AND ST_Intersects(route.geom,flood_zones.geom)),false),
 'hazard_intersection', COALESCE(bool_or(source IS DISTINCT FROM 'nws' AND ST_Intersects(route.geom,flood_zones.geom)),false))
FROM flood_zones CROSS JOIN route
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
    nws_warning = False
    segments: list[FlaggedSegment] = []
    exposure_rows = await conn.fetch(_EXPOSURE_SQL, geojson)
    for row in exposure_rows:
        nws_warning |= row["source"] == "nws"
        severity = _severity(row["severity"])
        hits.append(
            ExposureHit(
                zone_id=row["id"],
                source=row["source"],
                event=row["event"],
                severity=severity,
                length_m=float(row["len_m"]),
            )
        )
        segments.append(
            FlaggedSegment(
                source=row["source"],
                evidence="warning_area" if row["source"] == "nws" else "hazard_area",
                geometry=LineString(coordinates=json.loads(row["seg"])["coordinates"]),
                length_m=round(float(row["len_m"]), 1),
                flood_zone_id=row["id"],
                event=row["event"],
                severity=severity,
            )
        )

    nearest = await conn.fetchval(_NEAREST_SQL, geojson)
    intersections = json.loads(nearest) if isinstance(nearest,str) else nearest if isinstance(nearest,dict) else {}
    if intersections:
        nearest = intersections["nearest"]
    nearest_m = float(nearest) if nearest is not None else None
    warning_intersection = intersections.get("warning_intersection",nws_warning)
    hazard_intersection = intersections.get("hazard_intersection",any(h.source != "nws" for h in hits))

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
    severity_m = {}
    for hit in hits:
        if hit.source == "nws":
            severity_m[hit.severity.value] = severity_m.get(hit.severity.value, 0) + hit.length_m
    warning_m = sum(severity_m.values())
    hazard_m = sum(h.length_m for h in hits if h.source != "nws")
    from .ors import distance_m
    from ..models import LatLng
    edge_lengths = [distance_m(LatLng(lon=a[0],lat=a[1]),LatLng(lon=b[0],lat=b[1]))
                    for a,b in zip(geometry.coordinates,geometry.coordinates[1:])]
    # Use the same geodesic measurement as the SQL exposure denominator.
    for row in exposure_rows:
        if "edge" in row:
            edge_lengths[row["edge"]-1] = float(row["edge_m"])
    route_m = float(exposure_rows[0]["route_m"]) if exposure_rows and "route_m" in exposure_rows[0] else sum(edge_lengths)
    starts = [0.0]
    for length in edge_lengths: starts.append(starts[-1]+length)
    intervals = [(float(r.get("start_m", starts[r["edge"]-1]))+float(r["lo"])*float(r["edge_m"]),
                  float(r.get("start_m", starts[r["edge"]-1]))+float(r["hi"])*float(r["edge_m"]))
                 for r in exposure_rows if r["source"]=="nws" and "edge" in r]
    merged = union_intervals(intervals)
    initial_exit = merged[0][1] if merged and merged[0][0] < 0.1 else 0.0
    reentries = max(0,len(merged)-1)

    if hits:
        warnings.append(
            f"Unique NWS warning exposure: {warning_m / 1000:.2f} km. Hazard exposure: {hazard_m / 1000:.2f} km. These evidence categories may overlap; do not add them."
        )
    if warning_intersection:
        warnings.append("NWS polygons describe warning areas, not confirmed flooded roads. Road passability is unknown; never drive through observed floodwater.")
        if not warning_m:
            warnings.append("The route touches a warning boundary. Measured exposure is zero, but complete polygon avoidance is not established.")
        # Keep conservative exposure scoring, without equating an alert overlap
        # with observed water on a road.
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
        clear_of_flooding=not warning_intersection and not hazard_intersection,
        warning_intersection=warning_intersection, hazard_intersection=hazard_intersection,
        route_length_m=route_m,
        warning_exposure_m=warning_m,
        warning_exposure_percent=min(100,100*warning_m/route_m) if route_m else 0,
        warning_severity_m=severity_m, hazard_exposure_m=hazard_m,
        initial_warning_exit_m=initial_exit, warning_reentries=reentries,
    )


def _severity(value: str | None) -> FloodSeverity:
    if not value:
        return FloodSeverity.UNKNOWN
    try:
        return FloodSeverity(value.lower())
    except ValueError:
        return FloodSeverity.UNKNOWN


def union_intervals(intervals):
    """Union along-route intervals without double-counting overlapping alerts."""
    merged = []
    for lo,hi in sorted(intervals):
        if merged and lo <= merged[-1][1]+0.001:
            merged[-1] = (merged[-1][0],max(hi,merged[-1][1]))
        else:
            merged.append((lo,hi))
    return merged
