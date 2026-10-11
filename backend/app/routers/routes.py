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
    RiskBand,
    RoutePreference,
    RouteRequest,
    RouteResponse,
    SnapProposal,
)
from ..services import avoid_set as avoid_set_svc
from ..services import ors, risk, hazard_router

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["routing"])


@router.post("/routes", response_model=RouteResponse)
async def plan_routes(req: RouteRequest) -> RouteResponse:
    settings = get_settings()

    if settings.use_fixtures:
        return fixture_routes()
    if not settings.ors_api_key:
        raise HTTPException(status_code=503, detail="Routing API key is not configured.")

    seen = set()
    for snap in req.accepted_snaps:
        if (snap.endpoint in seen or getattr(req, snap.endpoint) != snap.proposed
                or ors.distance_m(snap.original, snap.proposed) > settings.road_snap_limit_m
                or abs(ors.distance_m(snap.original, snap.proposed) - snap.distance_m) > 1):
            raise HTTPException(status_code=422, detail="Invalid snapping confirmation. Select an entrance again.")
        seen.add(snap.endpoint)
    pool = db.pool()
    if req.accepted_snaps and pool is None:
        raise HTTPException(status_code=503, detail="Flood-risk assessment is unavailable. Confirmed road points cannot be routed until assessment is restored.")
    if pool is None:
        # No database means no flood data and no scoring. Still return a usable
        # route rather than an error, clearly labelled as unscored.
        return await _unscored_fallback(req)

    async with pool.acquire() as conn:
        try:
            async with asyncio.timeout(settings.routing_timeout_s):
                response = await _plan(conn, req)
        except TimeoutError as exc:
            raise HTTPException(status_code=503, detail="Route assessment exceeded its time budget. Travel safety cannot be confirmed.") from exc
        response.accepted_snaps = req.accepted_snaps
        if req.accepted_snaps:
            response.warnings.append("Road points were confirmed by the user. Building access is not verified; snapping does not establish route safety.")
        return response


# --------------------------------------------------------------------------- #


async def _plan(conn: asyncpg.Connection, req: RouteRequest) -> RouteResponse:
    settings = get_settings()
    warnings: list[str] = []

    zone_count = await avoid_set_svc.count_active_zones(conn)

    origin_inside = bool(zone_count and await avoid_set_svc.origin_in_warning(conn, req.origin))
    destination_inside = bool(zone_count and await avoid_set_svc.origin_in_warning(conn, req.destination))
    if origin_inside:
        warnings.append("The origin is inside an NWS warning area. Any departure begins inside that area, so complete warning-area avoidance may be impossible. This does not confirm flooded roads.")
    if destination_inside:
        warnings.append("The destination is inside an NWS warning area. Some warning exposure may be unavoidable; consider another destination or delaying travel.")

    # Establish a real baseline first, both for distance limits and snapping.
    try:
        baseline = await ors.directions(req.origin, req.destination, profile=req.profile, avoid_polygons=None)
    except ors.ORSLocationError as exc:
        return await _snap_proposal(req, exc)
    except ors.ORSError as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ors.ORSNoRoute)
                            else 503 if isinstance(exc, ors.ORSUnavailable) else 502,
                            detail=str(exc)) from exc
    plans = [(RouteLabel.FASTEST, None)]
    results = [baseline]
    calls = 1
    stopped = False
    search = req.preference != RoutePreference.FASTEST
    # <=4 directions calls per user request; no retries, stop on quota/auth errors.
    async def attempt(label, poly=None, **options):
        nonlocal calls, stopped
        if stopped or calls >= 4:
            return
        calls += 1
        try:
            if options.pop("alternatives", False):
                found = await ors.alternatives(req.origin, req.destination, profile=req.profile)
            else:
                found = [await ors.directions(req.origin, req.destination, profile=req.profile,
                                              avoid_polygons=poly, **options)]
            for route in found:
                if route.distance_m > baseline.distance_m * 1.75 or route.duration_s > baseline.duration_s * 2:
                    warnings.append("A detour was excluded because it exceeded the distance/time budget.")
                    continue
                plans.append((label, poly))
                results.append(route)
        except ors.ORSError as exc:
            warnings.append(f"Alternative search: {exc}")
            stopped = isinstance(exc, (ors.ORSRateLimited, ors.ORSCredentialsError, ors.ORSAccessDenied))

    # Real area avoidance takes priority over generic alternatives. Endpoint-
    # containing warnings cannot be hard-blocked; the weighted engine handles them.
    if zone_count and baseline.distance_m <= settings.max_route_km_with_avoidance * 1000:
        avoid = await avoid_set_svc.build(conn, req.origin, req.destination, include_warnings=search)
        warnings.extend(avoid.warnings)
        if avoid.geojson:
            await attempt(RouteLabel.ALTERNATIVE, avoid.geojson)
    elif zone_count:
        warnings.append("Trip exceeds the provider's 150 km area-avoidance limit; all returned routes are still flood-risk assessed.")

    if search and zone_count and not stopped and calls < 4:
        if settings.hazard_router_url and req.profile == "driving-car":
            calls += 1
            try:
                areas = await avoid_set_svc.hazard_areas(conn)
                weighted = await hazard_router.route(req.origin, req.destination, areas,
                    inside_warning=origin_inside or destination_inside)
                if weighted.distance_m <= baseline.distance_m*1.75 and weighted.duration_s <= baseline.duration_s*2:
                    plans.append((RouteLabel.ALTERNATIVE, True))
                    results.append(weighted)
                else:
                    warnings.append("Hazard-weighted detour exceeded the distance/time budget.")
            except ors.ORSError as exc:
                warnings.append(str(exc))
        else:
            warnings.append("Hazard-weighted road routing is unavailable. ORS cannot fully optimize large or endpoint-containing warning areas; candidate search is limited.")
    if search and baseline.distance_m < 100_000:
        await attempt(RouteLabel.ALTERNATIVE, alternatives=True)
    elif search:
        warnings.append("Trip exceeds the 100 km ORS alternative-route limit. Shortest-road and highway-avoidance requests are not substitutes for flood-warning avoidance.")

    # ---- dispose: score every candidate ourselves -------------------------- #
    candidates: list[RouteCandidate] = []
    seen: list[ors.RouteResult] = []
    baseline_candidate = None

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

        # Only exact duplicates can be discarded before assessment. Nearby roads
        # can sit on opposite sides of a warning/hazard boundary.
        if any(result.geometry.coordinates == prior.geometry.coordinates for prior in seen):
            continue
        seen.append(result)

        assessment = await risk.assess(conn, result.geometry)

        candidate_warnings = list(assessment.warnings)
        if poly is not None and not assessment.clear_of_flooding:
            candidate_warnings.append(
                "Flood avoidance was requested but the routing service returned a "
                "route that still intersects an active warning or hazard area."
            )

        candidate = RouteCandidate(
                id=f"{label.value}-{uuid4().hex[:8]}",
                label=label,
                geometry=result.geometry,
                distance_m=assessment.route_length_m or result.distance_m,
                duration_s=round(result.duration_s, 1),
                risk_score=assessment.breakdown.total,
                risk_band=assessment.band,
                risk_breakdown=assessment.breakdown,
                flagged_segments=assessment.flagged_segments,
                min_elevation_m=assessment.min_elevation_m,
                max_elevation_m=assessment.max_elevation_m,
                elevation_profile=_profile(result.geometry, assessment.route_length_m or result.distance_m),
                avoidance_requested=poly is not None,
                avoidance_verified=assessment.clear_of_flooding,
                warning_exposure_m=assessment.warning_exposure_m,
                warning_exposure_percent=assessment.warning_exposure_percent,
                warning_severity_m=assessment.warning_severity_m,
                hazard_exposure_m=assessment.hazard_exposure_m,
                initial_warning_exit_m=assessment.initial_warning_exit_m,
                warning_reentries=assessment.warning_reentries,
                warning_avoidance_achieved=assessment.warning_exposure_m == 0 and not assessment.warning_intersection,
                warnings=candidate_warnings,
            )
        if label == RouteLabel.FASTEST:
            baseline_candidate = candidate
        if assessment.hazard_exposure_m > 0 or assessment.hazard_intersection:
            warnings.append("A candidate intersecting a recorded non-NWS hazard area was excluded. No route through known hazards is offered.")
            continue
        candidates.append(candidate)

    if not candidates:
        if baseline_candidate is not None:
            return RouteResponse(request_id=uuid4(), generated_at=datetime.now(UTC), routes=[],
                flood_zones_considered=zone_count, no_lower_risk_route_found=True,
                warnings=warnings+[NO_LOWER_EXPOSURE])
        if isinstance(results[0], ors.ORSLocationError):
            return await _snap_proposal(req, results[0])
        raise HTTPException(
            status_code=(422 if isinstance(results[0], (ors.ORSLocationError, ors.ORSNoRoute))
                         else 503 if all(isinstance(r, ors.ORSUnavailable) for r in results) else 502),
            detail="No route could be computed. " + (" ".join(warnings) or ""),
        )

    candidates.sort(key=_exposure_key if req.preference == RoutePreference.SAFEST else lambda c: (c.risk_score, c.duration_s))

    if all(not c.avoidance_verified for c in candidates) and zone_count:
        warnings.append(
            "Every available route intersects an active warning or hazard area. This does not confirm flooded roads. The least-exposed "
            "option is shown — consider delaying travel."
        )

    recommended = _recommend(candidates, req.preference)
    lower_found = any(_warning_key(c) < _warning_key(baseline_candidate) for c in candidates)
    no_lower = search and (recommended is None or (not lower_found and not any(c.avoidance_verified for c in candidates)))
    if no_lower:
        warnings.append(NO_LOWER_EXPOSURE)
        recommended = None
    if recommended is None:
        warnings.append("Evaluated routes are for information only, not safe navigation guidance. Avoid travel through floodwater; consider delaying travel.")
    request_id = uuid4()

    await _persist(conn, request_id, req, recommended)

    return RouteResponse(
        request_id=request_id,
        generated_at=datetime.now(UTC),
        routes=candidates,
        recommended_id=recommended.id if recommended else None,
        flood_zones_considered=zone_count,
        no_lower_risk_route_found=no_lower,
        warnings=warnings,
    )


NO_LOWER_EXPOSURE = "No lower-exposure route found. Travel safety cannot be confirmed."


def _warning_key(c: RouteCandidate):
    severity = c.warning_severity_m
    return (not c.warning_avoidance_achieved,
            *(severity.get(s, 0) for s in ("extreme", "severe", "moderate", "unknown", "minor")),
            c.warning_exposure_m, c.initial_warning_exit_m, c.warning_reentries)


def _exposure_key(c: RouteCandidate):
    """Evidence first; highest severity dominates. Never rank by a saturated score."""
    return (c.hazard_exposure_m, c.risk_breakdown.gauge_proximity,
            *_warning_key(c), c.risk_breakdown.low_lying, c.duration_s)


def _same_corridor(a: ors.RouteResult, b: ors.RouteResult) -> bool:
    """Compare sampled route geometry, never distance/time buckets alone."""
    def samples(route):
        coords = route.geometry.coordinates
        lengths = [0.0]
        for p, q in zip(coords, coords[1:]):
            lengths.append(lengths[-1] + ors.distance_m(LatLng(lon=p[0], lat=p[1]), LatLng(lon=q[0], lat=q[1])))
        out = []
        j = 1
        for i in range(33):
            target = lengths[-1] * i / 32
            while j < len(coords)-1 and lengths[j] < target:
                j += 1
            fraction = (target-lengths[j-1]) / (lengths[j]-lengths[j-1] or 1)
            out.append(LatLng(lon=coords[j-1][0]+fraction*(coords[j][0]-coords[j-1][0]),
                              lat=coords[j-1][1]+fraction*(coords[j][1]-coords[j-1][1])))
        return out
    return sum(ors.distance_m(p,q) < 100 for p,q in zip(samples(a),samples(b))) >= 30


def _recommend(
    candidates: list[RouteCandidate], preference: RoutePreference
) -> RouteCandidate | None:
    if preference == RoutePreference.SAFEST:
        best = min(candidates, key=_exposure_key) if candidates else None
        return best if best and best.risk_band != RiskBand.DANGEROUS else None
    candidates = [c for c in candidates if c.risk_band != RiskBand.DANGEROUS]
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

    return min(candidates, key=_exposure_key)


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


async def _snap_proposal(req: RouteRequest, error: ors.ORSLocationError) -> RouteResponse:
    manual = "Select a public-road entrance or nearby address. Building access cannot be inferred from the nearest road."
    if req.profile != "driving-car" or req.accepted_snaps or not error.endpoint_indices:
        raise HTTPException(status_code=422, detail=f"{error} {manual}")
    names = ["origin" if i == 0 else "destination" for i in error.endpoint_indices]
    points = [getattr(req, name) for name in names]
    try:
        proposed = await ors.snap_points(points)
    except ors.ORSError as exc:
        raise HTTPException(status_code=422, detail=f"{exc} {manual}") from exc
    if any(point is None for point in proposed):
        raise HTTPException(status_code=422, detail=f"No acceptable road point within {get_settings().road_snap_limit_m:g} metres. {manual}")
    proposals = [SnapProposal(endpoint=name, original=original, proposed=point,
                              distance_m=round(ors.distance_m(original, point), 1))
                 for name, original, point in zip(names, points, proposed, strict=True)]
    return RouteResponse(request_id=uuid4(), generated_at=datetime.now(UTC), routes=[],
        snap_proposals=proposals,
        warnings=["Confirmation required. Network proximity does not establish public access, building access or flood safety."])


async def _unscored_fallback(req: RouteRequest) -> RouteResponse:
    """ORS is configured but the database is not: route, but do not pretend to score."""
    from ..models import RiskBand, RiskBreakdown

    try:
        result = await ors.directions(req.origin, req.destination, profile=req.profile)
    except ors.ORSLocationError as exc:
        return await _snap_proposal(req, exc)
    except ors.ORSNoRoute as exc:
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
