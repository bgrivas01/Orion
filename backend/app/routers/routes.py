"""POST /api/routes — the main endpoint.

Flow: ask ORS for several candidates, then score every one of them ourselves in
PostGIS and rank. Never assume ORS honoured an avoid polygon.
"""

import asyncio
import json
import logging
import math
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, HTTPException

from .. import db
from ..config import get_settings
from ..fixtures import fixture_routes
from ..models import (
    LatLng,
    RouteCandidate,
    RouteLabel,
    RoutePreference,
    RouteRequest,
    RouteResponse,
)
from ..services import avoid_set as avoid_set_svc
from ..services import ors, risk

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["routing"])


@router.post("/routes", response_model=RouteResponse)
async def plan_routes(req: RouteRequest) -> RouteResponse:
    settings = get_settings()

    if settings.use_fixtures:
        return fixture_routes()
    if not settings.ors_api_key:
        raise HTTPException(status_code=503, detail="Routing API key is not configured.")

    pool = db.pool()
    if pool is None:
        # No database means no flood data and no scoring. Still return a usable
        # route rather than an error, clearly labelled as unscored.
        return await _unscored_fallback(req)

    async with pool.acquire() as conn:
        return await _plan(conn, req)


# --------------------------------------------------------------------------- #


async def _plan(conn: asyncpg.Connection, req: RouteRequest) -> RouteResponse:
    settings = get_settings()
    warnings: list[str] = []

    zone_count = await avoid_set_svc.count_active_zones(conn)

    straight_km = _haversine_km(req.origin, req.destination)
    avoidance_allowed = straight_km <= settings.max_route_km_with_avoidance
    if not avoidance_allowed:
        warnings.append(
            f"Trip is ~{straight_km:.0f} km; the routing service cannot apply flood "
            f"avoidance above {settings.max_route_km_with_avoidance:.0f} km. Routes are "
            "still scored and ranked by flood risk."
        )

    # ---- build the avoid sets (cheap, one DB round-trip each) -------------- #
    avoid_all = avoid_high = None
    if avoidance_allowed and zone_count:
        avoid_all = await avoid_set_svc.build(conn, req.origin, req.destination)
        avoid_high = await avoid_set_svc.build(
            conn, req.origin, req.destination, high_severity_only=True
        )
        warnings.extend(avoid_all.warnings)

    # ---- propose: one ORS call per candidate ------------------------------- #
    plans: list[tuple[RouteLabel, dict | None]] = [(RouteLabel.FASTEST, None)]
    if avoid_all and avoid_all.geojson:
        plans.append((RouteLabel.SAFEST, avoid_all.geojson))
    if (
        avoid_high
        and avoid_high.geojson
        and avoid_all
        and avoid_high.geojson != avoid_all.geojson
    ):
        plans.append((RouteLabel.BALANCED, avoid_high.geojson))

    results = await asyncio.gather(
        *(
            ors.directions(
                req.origin, req.destination, profile=req.profile, avoid_polygons=poly
            )
            for _, poly in plans
        ),
        return_exceptions=True,
    )

    # ---- dispose: score every candidate ourselves -------------------------- #
    candidates: list[RouteCandidate] = []
    seen: set[tuple[int, int]] = set()

    for (label, poly), result in zip(plans, results, strict=True):
        if isinstance(result, ors.ORSUnavailable):
            warnings.append(f"Routing service unavailable for the {label.value} route: {result}")
            log.warning("ORS unavailable for %s: %s", label.value, result)
            continue
        if isinstance(result, ors.ORSError):
            warnings.append(f"Could not compute the {label.value} route: {result}")
            log.warning("ORS failed for %s: %s", label.value, result)
            continue

        if isinstance(result, BaseException):
            log.error("Route candidate failed label=%s category=internal", label.value)
            warnings.append(f"Internal routing failure for the {label.value} route.")
            continue

        # Collapse candidates that came back effectively identical — common when
        # ORS ignores the avoid polygon entirely.
        key = (int(result.distance_m / 50), int(result.duration_s / 30))
        if key in seen:
            log.info("%s route is a duplicate of an earlier candidate", label.value)
            continue
        seen.add(key)

        assessment = await risk.assess(conn, result.geometry)

        candidate_warnings = list(assessment.warnings)
        if poly is not None and not assessment.clear_of_flooding:
            candidate_warnings.append(
                "Flood avoidance was requested but the routing service returned a "
                "route that still intersects an active warning or hazard area."
            )

        candidates.append(
            RouteCandidate(
                id=f"{label.value}-{uuid4().hex[:8]}",
                label=label,
                geometry=result.geometry,
                distance_m=round(result.distance_m, 1),
                duration_s=round(result.duration_s, 1),
                risk_score=assessment.breakdown.total,
                risk_band=assessment.band,
                risk_breakdown=assessment.breakdown,
                flagged_segments=assessment.flagged_segments,
                min_elevation_m=assessment.min_elevation_m,
                max_elevation_m=assessment.max_elevation_m,
                elevation_profile=_profile(result.geometry, result.distance_m),
                avoidance_requested=poly is not None,
                avoidance_verified=assessment.clear_of_flooding,
                warnings=candidate_warnings,
            )
        )

    if not candidates:
        raise HTTPException(
            status_code=(422 if isinstance(results[0], (ors.ORSLocationError, ors.ORSNoRoute))
                         else 503 if all(isinstance(r, ors.ORSUnavailable) for r in results) else 502),
            detail="No route could be computed. " + (" ".join(warnings) or ""),
        )

    candidates.sort(key=lambda c: (c.risk_score, c.duration_s))

    if all(not c.avoidance_verified for c in candidates) and zone_count:
        warnings.append(
            "Every available route intersects an active warning or hazard area. This does not confirm flooded roads. The least-exposed "
            "option is shown — consider delaying travel."
        )

    recommended = _recommend(candidates, req.preference)
    request_id = uuid4()

    await _persist(conn, request_id, req, recommended)

    return RouteResponse(
        request_id=request_id,
        generated_at=datetime.now(UTC),
        routes=candidates,
        recommended_id=recommended.id if recommended else None,
        flood_zones_considered=zone_count,
        warnings=warnings,
    )


def _recommend(
    candidates: list[RouteCandidate], preference: RoutePreference
) -> RouteCandidate | None:
    if not candidates:
        return None

    if preference is RoutePreference.FASTEST:
        # Still refuse to recommend driving into water; fall back to the safest.
        passable = [c for c in candidates if c.avoidance_verified]
        pool = passable or candidates
        return min(pool, key=lambda c: c.duration_s)

    if preference is RoutePreference.BALANCED:
        # Normalise time against the quickest option and trade it off 50/50.
        quickest = min(c.duration_s for c in candidates) or 1.0
        return min(
            candidates,
            key=lambda c: 0.5 * (c.risk_score / 100.0)
            + 0.5 * ((c.duration_s / quickest) - 1.0),
        )

    return min(candidates, key=lambda c: (c.risk_score, c.duration_s))


def _profile(geometry, distance_m: float):
    from ..models import ElevationPoint

    coords = geometry.coordinates
    n = len(coords) - 1
    if n <= 0:
        return []
    return [
        ElevationPoint(distance_m=round(distance_m * i / n, 1), elevation_m=c[2])
        for i, c in enumerate(coords)
        if len(c) > 2
    ]


async def _persist(
    conn: asyncpg.Connection,
    request_id: UUID,
    req: RouteRequest,
    recommended: RouteCandidate | None,
) -> None:
    try:
        await conn.execute(
            """
            INSERT INTO route_requests
                (time, request_id, origin, destination, chosen, risk_score)
            VALUES (now(), $1,
                    ST_SetSRID(ST_MakePoint($2, $3), 4326),
                    ST_SetSRID(ST_MakePoint($4, $5), 4326),
                    $6, $7)
            """,
            request_id,
            req.origin.lon,
            req.origin.lat,
            req.destination.lon,
            req.destination.lat,
            recommended.label.value if recommended else None,
            recommended.risk_score if recommended else None,
        )
    except Exception as exc:  # noqa: BLE001 - history is nice to have, not critical
        log.warning("could not record route request: %s", exc)


async def _unscored_fallback(req: RouteRequest) -> RouteResponse:
    """ORS is configured but the database is not: route, but do not pretend to score."""
    from ..models import RiskBand, RiskBreakdown

    try:
        result = await ors.directions(req.origin, req.destination, profile=req.profile)
    except (ors.ORSLocationError, ors.ORSNoRoute) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ors.ORSUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ors.ORSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    elevations = risk.elevations_of(result.geometry)
    low = risk.low_lying_score(elevations)

    return RouteResponse(
        request_id=uuid4(),
        generated_at=datetime.now(UTC),
        routes=[
            RouteCandidate(
                id=f"unscored-{uuid4().hex[:8]}",
                label=RouteLabel.FASTEST,
                geometry=result.geometry,
                distance_m=round(result.distance_m, 1),
                duration_s=round(result.duration_s, 1),
                risk_score=round(low, 2),
                risk_band=RiskBand.CAUTION,
                risk_breakdown=RiskBreakdown(
                    flood_exposure=0.0,
                    low_lying=round(low, 2),
                    gauge_proximity=0.0,
                    approach_margin=0.0,
                    total=round(low, 2),
                ),
                min_elevation_m=min(elevations) if elevations else None,
                max_elevation_m=max(elevations) if elevations else None,
                elevation_profile=_profile(result.geometry, result.distance_m),
                warnings=["No flood database connected — this route is NOT flood-checked."],
            )
        ],
        flood_zones_considered=0,
        warnings=["DATABASE_URL is not configured, so flood risk could not be assessed."],
    )


def _haversine_km(a: LatLng, b: LatLng) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
