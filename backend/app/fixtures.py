"""Deterministic demo data.

Two jobs:
  1. Hour-one unblocking: the frontends get contract-shaped JSON from
     POST /api/routes before TigerData or the ORS key exist (USE_FIXTURES=true).
  2. Demo insurance: if nothing in the US is flooding on demo day, the seed
     script pushes these polygons into the database so the story still works.

Scenario: downtown Houston -> George Bush Intercontinental (IAH), with a flash
flood warning sitting across the direct I-45 corridor near Little White Oak
Bayou. The fastest route drives through it; the safest route swings east.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from .models import (
    ElevationPoint,
    FlaggedSegment,
    FloodSeverity,
    FloodZone,
    Gauge,
    GaugeReading,
    GaugeStatus,
    GaugeTrend,
    LineString,
    MultiPolygon,
    RiskBand,
    RiskBreakdown,
    RouteCandidate,
    RouteLabel,
    RouteResponse,
)

ORIGIN = (-95.3698, 29.7604)  # downtown Houston
DESTINATION = (-95.3368, 29.9902)  # IAH

# Flash flood warning polygon straddling the I-45 N corridor.
FLOOD_POLYGON: list[list[list[float]]] = [
    [
        [-95.4050, 29.8180],
        [-95.3520, 29.8180],
        [-95.3480, 29.8460],
        [-95.3900, 29.8520],
        [-95.4080, 29.8360],
        [-95.4050, 29.8180],
    ]
]

# A second, smaller zone on a bayou to the west — tests multi-zone handling.
FLOOD_POLYGON_WEST: list[list[list[float]]] = [
    [
        [-95.4600, 29.7850],
        [-95.4320, 29.7850],
        [-95.4300, 29.8050],
        [-95.4620, 29.8060],
        [-95.4600, 29.7850],
    ]
]


def _now() -> datetime:
    return datetime.now(UTC)


def _lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> list[float]:
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def _path(waypoints: list[tuple[float, float]], per_leg: int = 14) -> list[list[float]]:
    """Interpolate a polyline through waypoints so it renders like a real route."""
    coords: list[list[float]] = []
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        steps = per_leg if i < len(waypoints) - 2 else per_leg + 1
        for s in range(steps):
            coords.append(_lerp(a, b, s / per_leg))
    coords.append([waypoints[-1][0], waypoints[-1][1]])
    return coords


def _with_elevation(coords: list[list[float]], base: float, dip_at: float | None) -> list[list[float]]:
    """Attach a third ordinate, mimicking the 3D geometry ORS returns.

    `dip_at` is a 0-1 position along the route where terrain drops into a bayou
    bottom — that dip is what the low-lying component of the risk score sees.
    """
    out = []
    n = len(coords) - 1
    for i, c in enumerate(coords):
        t = i / n if n else 0
        elev = base + 6.0 * t
        if dip_at is not None:
            # Gaussian dip of ~9m around dip_at.
            elev -= 9.0 * pow(2.718281828, -(((t - dip_at) / 0.08) ** 2))
        out.append([c[0], c[1], round(elev, 1)])
    return out


def _profile(coords: list[list[float]], distance_m: float) -> list[ElevationPoint]:
    n = len(coords) - 1
    return [
        ElevationPoint(distance_m=round(distance_m * i / n, 1), elevation_m=c[2])
        for i, c in enumerate(coords)
        if len(c) > 2
    ]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

_FASTEST_COORDS = _with_elevation(
    _path([ORIGIN, (-95.3730, 29.8200), (-95.3690, 29.8400), (-95.3600, 29.9100), DESTINATION]),
    base=13.0,
    dip_at=0.33,  # drops into the flooded bayou
)
_BALANCED_COORDS = _with_elevation(
    _path([ORIGIN, (-95.3550, 29.8150), (-95.3450, 29.8500), (-95.3450, 29.9200), DESTINATION]),
    base=15.0,
    dip_at=0.36,
)
_SAFEST_COORDS = _with_elevation(
    _path([ORIGIN, (-95.3300, 29.7900), (-95.3050, 29.8600), (-95.3100, 29.9400), DESTINATION]),
    base=19.0,
    dip_at=None,  # stays on the ridge east of the bayou
)


def fixture_routes() -> RouteResponse:
    fastest = RouteCandidate(
        id="fx-fastest",
        label=RouteLabel.FASTEST,
        geometry=LineString(coordinates=_FASTEST_COORDS),
        distance_m=31_400,
        duration_s=1_560,
        risk_score=78.4,
        risk_band=RiskBand.DANGEROUS,
        risk_breakdown=RiskBreakdown(
            flood_exposure=44.0, low_lying=19.2, gauge_proximity=13.1, approach_margin=2.1,
            total=78.4,
        ),
        flagged_segments=[
            FlaggedSegment(
                geometry=LineString(
                    coordinates=[c[:2] for c in _FASTEST_COORDS[13:22]],
                ),
                length_m=3_150,
                flood_zone_id="fx-zone-i45",
                event="Flash Flood Warning",
                severity=FloodSeverity.SEVERE,
            )
        ],
        min_elevation_m=min(c[2] for c in _FASTEST_COORDS),
        max_elevation_m=max(c[2] for c in _FASTEST_COORDS),
        elevation_profile=_profile(_FASTEST_COORDS, 31_400),
        avoidance_requested=False,
        avoidance_verified=False,
        warnings=["Crosses an active Flash Flood Warning for 3.2 km on I-45 N."],
    )

    balanced = RouteCandidate(
        id="fx-balanced",
        label=RouteLabel.BALANCED,
        geometry=LineString(coordinates=_BALANCED_COORDS),
        distance_m=34_900,
        duration_s=1_810,
        risk_score=41.6,
        risk_band=RiskBand.CAUTION,
        risk_breakdown=RiskBreakdown(
            flood_exposure=12.0, low_lying=16.4, gauge_proximity=9.2, approach_margin=4.0,
            total=41.6,
        ),
        flagged_segments=[
            FlaggedSegment(
                geometry=LineString(coordinates=[c[:2] for c in _BALANCED_COORDS[15:19]]),
                length_m=820,
                flood_zone_id="fx-zone-i45",
                event="Flash Flood Warning",
                severity=FloodSeverity.SEVERE,
            )
        ],
        min_elevation_m=min(c[2] for c in _BALANCED_COORDS),
        max_elevation_m=max(c[2] for c in _BALANCED_COORDS),
        elevation_profile=_profile(_BALANCED_COORDS, 34_900),
        avoidance_requested=True,
        avoidance_verified=False,
        warnings=["Clips the edge of a flood warning for 0.8 km."],
    )

    safest = RouteCandidate(
        id="fx-safest",
        label=RouteLabel.SAFEST,
        geometry=LineString(coordinates=_SAFEST_COORDS),
        distance_m=38_600,
        duration_s=2_040,
        risk_score=8.2,
        risk_band=RiskBand.SAFE,
        risk_breakdown=RiskBreakdown(
            flood_exposure=0.0, low_lying=3.1, gauge_proximity=4.6, approach_margin=0.5,
            total=8.2,
        ),
        flagged_segments=[],
        min_elevation_m=min(c[2] for c in _SAFEST_COORDS),
        max_elevation_m=max(c[2] for c in _SAFEST_COORDS),
        elevation_profile=_profile(_SAFEST_COORDS, 38_600),
        avoidance_requested=True,
        avoidance_verified=True,
        warnings=[],
    )

    return RouteResponse(
        request_id=UUID("00000000-0000-4000-8000-000000000001"),
        generated_at=_now(),
        routes=[safest, balanced, fastest],
        recommended_id="fx-safest",
        flood_zones_considered=2,
        warnings=["Serving fixture data (USE_FIXTURES=true)."],
    )


# --------------------------------------------------------------------------- #
# Flood zones
# --------------------------------------------------------------------------- #


def fixture_flood_zones() -> list[FloodZone]:
    now = _now()
    return [
        FloodZone(
            id="fx-zone-i45",
            source="demo",
            event="Flash Flood Warning",
            severity=FloodSeverity.SEVERE,
            headline="Flash Flood Warning for Little White Oak Bayou until 8:00 PM CDT",
            geometry=MultiPolygon(coordinates=[FLOOD_POLYGON]),
            effective=now - timedelta(hours=1),
            expires=now + timedelta(hours=5),
        ),
        FloodZone(
            id="fx-zone-west",
            source="demo",
            event="Flood Warning",
            severity=FloodSeverity.MODERATE,
            headline="Flood Warning for Buffalo Bayou near Piney Point",
            geometry=MultiPolygon(coordinates=[FLOOD_POLYGON_WEST]),
            effective=now - timedelta(hours=3),
            expires=now + timedelta(hours=8),
        ),
    ]


# --------------------------------------------------------------------------- #
# Gauges
# --------------------------------------------------------------------------- #


def fixture_gauges() -> list[Gauge]:
    now = _now()

    def series(start: float, delta: float) -> list[GaugeReading]:
        return [
            GaugeReading(
                time=now - timedelta(hours=23 - i),
                gauge_height_ft=round(start + delta * i, 2),
            )
            for i in range(24)
        ]

    return [
        Gauge(
            site_id="08074500",
            name="Little White Oak Bayou at Trimble St, Houston",
            lat=29.8033,
            lon=-95.3772,
            current_ft=27.4,
            flood_stage_ft=24.0,
            action_stage_ft=20.0,
            status=GaugeStatus.FLOOD,
            trend=GaugeTrend.RISING,
            series=series(18.2, 0.4),
        ),
        Gauge(
            site_id="08074000",
            name="Buffalo Bayou at Piney Point, Houston",
            lat=29.7527,
            lon=-95.5203,
            current_ft=21.6,
            flood_stage_ft=24.0,
            action_stage_ft=20.0,
            status=GaugeStatus.ACTION,
            trend=GaugeTrend.RISING,
            series=series(15.1, 0.28),
        ),
        Gauge(
            site_id="08076000",
            name="Greens Bayou near Houston",
            lat=29.8869,
            lon=-95.3089,
            current_ft=9.8,
            flood_stage_ft=18.0,
            action_stage_ft=14.0,
            status=GaugeStatus.NORMAL,
            trend=GaugeTrend.STEADY,
            series=series(9.9, -0.01),
        ),
    ]
