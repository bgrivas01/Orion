"""Wire contract for the Orion API.

Both the web and mobile clients generate their TypeScript types from the OpenAPI
schema FastAPI derives from this module, so treat every change here as a change
to a shared contract.
"""

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


class LatLng(BaseModel):
    lat: float = Field(..., ge=-90, le=90, examples=[29.7604])
    lon: float = Field(..., ge=-180, le=180, examples=[-95.3698])


class LineString(BaseModel):
    """GeoJSON LineString. Coordinates are [lon, lat] or [lon, lat, elevation_m]."""

    type: Literal["LineString"] = "LineString"
    coordinates: list[list[float]]


class MultiPolygon(BaseModel):
    """GeoJSON MultiPolygon in [lon, lat] order."""

    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: list[list[list[list[float]]]]


class Place(BaseModel):
    """A geocoding result."""

    name: str
    lat: float
    lon: float
    region: str | None = None


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class RiskBand(str, Enum):
    SAFE = "safe"
    CAUTION = "caution"
    DANGEROUS = "dangerous"


class FloodSeverity(str, Enum):
    EXTREME = "extreme"
    SEVERE = "severe"
    MODERATE = "moderate"
    MINOR = "minor"
    UNKNOWN = "unknown"


class RouteLabel(str, Enum):
    ALTERNATIVE = "alternative"
    FASTEST = "fastest"
    BALANCED = "balanced"
    SAFEST = "safest"


class GaugeStatus(str, Enum):
    NORMAL = "normal"
    ACTION = "action"
    FLOOD = "flood"
    UNKNOWN = "unknown"


class GaugeTrend(str, Enum):
    RISING = "rising"
    FALLING = "falling"
    STEADY = "steady"
    UNKNOWN = "unknown"


class RoutePreference(str, Enum):
    """How hard the caller wants us to trade time for safety."""

    SAFEST = "safest"
    BALANCED = "balanced"
    FASTEST = "fastest"


# --------------------------------------------------------------------------- #
# Flood zones
# --------------------------------------------------------------------------- #


class FloodZone(BaseModel):
    id: str
    source: str = Field(..., examples=["nws"], description="nws | noaa_fim | demo")
    event: str = Field(..., examples=["Flash Flood Warning"])
    severity: FloodSeverity
    headline: str | None = None
    geometry: MultiPolygon
    effective: datetime | None = None
    expires: datetime | None = None


class FloodZoneSummary(BaseModel):
    """Flood zone without geometry — for compact lists and alert payloads."""

    id: str
    event: str
    severity: FloodSeverity
    headline: str | None = None
    expires: datetime | None = None
    distance_m: float | None = Field(
        None, description="Distance from the queried point, when queried by location."
    )


class FloodReport(BaseModel):
    id: str = Field(..., description="Database bigint represented as a string for JS precision.")
    location_name: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    water_depth_inches: float | None = None
    severity: str | None = None
    description: str | None = None
    reported_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


class FlaggedSegment(BaseModel):
    source: str = "unknown"
    evidence: Literal["warning_area", "hazard_area"] = "hazard_area"
    """A stretch of route that intersects a flood zone. The map paints these red."""

    geometry: LineString
    length_m: float
    flood_zone_id: str
    event: str
    severity: FloodSeverity


class RiskBreakdown(BaseModel):
    """Per-component contribution to the total score. Each is already weighted."""

    flood_exposure: float = Field(..., description="0-50")
    low_lying: float = Field(..., description="0-25")
    gauge_proximity: float = Field(..., description="0-20")
    approach_margin: float = Field(..., description="0-5")
    total: float = Field(..., ge=0, le=100)


class ElevationPoint(BaseModel):
    distance_m: float
    elevation_m: float


class RouteCandidate(BaseModel):
    warning_exposure_m: float = Field(0, ge=0)
    warning_exposure_percent: float = Field(0, ge=0, le=100)
    warning_severity_m: dict[str, float] = Field(default_factory=dict)
    hazard_exposure_m: float = Field(0, ge=0)
    initial_warning_exit_m: float = Field(0, ge=0)
    warning_reentries: int = Field(0, ge=0)
    warning_avoidance_achieved: bool = False
    id: str
    label: RouteLabel
    geometry: LineString
    distance_m: float
    duration_s: float
    risk_score: float = Field(..., ge=0, le=100, description="0 = safest, 100 = worst")
    risk_band: RiskBand
    risk_breakdown: RiskBreakdown
    flagged_segments: list[FlaggedSegment] = []
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    elevation_profile: list[ElevationPoint] = []
    avoidance_requested: bool = Field(
          False, description="Whether polygon avoidance or hazard-weighted road routing was requested."
    )
    avoidance_verified: bool = Field(
        False,
        description=(
            "True only if we confirmed in PostGIS that the returned geometry is clear of "
            "all active flood zones. ORS avoid_polygons is unreliable, so this is the "
            "polygon-overlap check, not proof of road passability or observed flooding."
        ),
    )
    warnings: list[str] = []


class SnapProposal(BaseModel):
    endpoint: Literal["origin", "destination"]
    original: LatLng
    proposed: LatLng
    distance_m: float = Field(ge=0)
    confirmation_required: Literal[True] = True
    access_verified: Literal[False] = False


class SnapConfirmation(SnapProposal):
    public_access_confirmed: Literal[True]


class RouteRequest(BaseModel):
    accepted_snaps: list[SnapConfirmation] = Field(default_factory=list, max_length=2)
    origin: LatLng
    destination: LatLng
    profile: str = Field("driving-car", examples=["driving-car", "foot-walking"])
    preference: RoutePreference = RoutePreference.SAFEST


class RouteResponse(BaseModel):
    no_lower_risk_route_found: bool = False
    snap_proposals: list[SnapProposal] = Field(default_factory=list)
    accepted_snaps: list[SnapConfirmation] = Field(default_factory=list)
    request_id: UUID
    generated_at: datetime
    routes: list[RouteCandidate]
    recommended_id: str | None = None
    flood_zones_considered: int = 0
    warnings: list[str] = Field(
        [],
        description="Request-level warnings, e.g. all candidates cross water, or avoidance skipped.",
    )


# --------------------------------------------------------------------------- #
# Gauges
# --------------------------------------------------------------------------- #


class GaugeReading(BaseModel):
    time: datetime
    gauge_height_ft: float | None = None


class Gauge(BaseModel):
    site_id: str
    name: str
    lat: float
    lon: float
    current_ft: float | None = None
    flood_stage_ft: float | None = None
    action_stage_ft: float | None = None
    status: GaugeStatus = GaugeStatus.UNKNOWN
    trend: GaugeTrend = GaugeTrend.UNKNOWN
    series: list[GaugeReading] = Field([], description="Hourly buckets, most recent last.")


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #


class AlertCheckResponse(BaseModel):
    in_flood_zone: bool
    nearest_distance_m: float | None = None
    zones: list[FloodZoneSummary] = []
    message: str


class AlertSubscription(BaseModel):
    device_id: str
    location: LatLng
    radius_m: int = Field(5000, ge=100, le=100_000)
    active_route: LineString | None = Field(
        None, description="If set, we also alert on new zones intersecting this route."
    )


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    ors: bool
    postgis: bool = False
    timescaledb: bool = False
    active_flood_zones: int | None = None
    detail: str | None = None
