"""Proximity alerts for the mobile app.

Remote push does not work in Expo Go (removed in SDK 53), so the phone polls
/api/alerts/check in the foreground and raises a *local* notification. The
WebSocket is the nicer path for the web app and for a future dev build.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from .. import db
from ..config import get_settings
from ..fixtures import fixture_flood_zones
from ..models import AlertCheckResponse, AlertSubscription, FloodZoneSummary
from ..services.avoid_set import severity_from_text

log = logging.getLogger(__name__)

router = APIRouter(tags=["alerts"])

_CHECK_SQL = """
SELECT id, event, severity, headline, expires,
       ST_Distance(
           ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
           geom::geography
       ) AS distance_m,
       ST_Contains(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)) AS inside
FROM flood_zones
WHERE (expires IS NULL OR expires > now())
  AND ST_DWithin(
          ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
          geom::geography,
          $3
      )
ORDER BY distance_m
LIMIT 20
"""


@router.get("/api/alerts/check", response_model=AlertCheckResponse)
async def check_alerts(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(5000, ge=100, le=100_000),
) -> AlertCheckResponse:
    """Is this point in, or near, an active flood zone?"""
    settings = get_settings()
    pool = db.pool()

    if settings.use_fixtures or pool is None:
        zones = [
            FloodZoneSummary(
                id=z.id,
                event=z.event,
                severity=z.severity,
                headline=z.headline,
                expires=z.expires,
                distance_m=0.0,
            )
            for z in fixture_flood_zones()[:1]
        ]
        return AlertCheckResponse(
            in_flood_zone=True,
            nearest_distance_m=0.0,
            zones=zones,
            message="Fixture mode: pretending you are inside a Flash Flood Warning.",
        )

    async with pool.acquire() as conn:
        rows = await conn.fetch(_CHECK_SQL, lon, lat, radius_m)

    if not rows:
        return AlertCheckResponse(
            in_flood_zone=False,
            nearest_distance_m=None,
            zones=[],
            message="No active flood warnings near you.",
        )

    inside = any(r["inside"] for r in rows)
    nearest = float(rows[0]["distance_m"])
    zones = [
        FloodZoneSummary(
            id=r["id"],
            event=r["event"],
            severity=severity_from_text(r["severity"]),
            headline=r["headline"],
            expires=r["expires"],
            distance_m=round(float(r["distance_m"]), 1),
        )
        for r in rows
    ]

    if inside:
        message = f"You are inside an active {zones[0].event}. Move to higher ground."
    else:
        message = (
            f"{zones[0].event} {nearest / 1000:.1f} km away. Avoid travelling toward it."
        )

    return AlertCheckResponse(
        in_flood_zone=inside,
        nearest_distance_m=round(nearest, 1),
        zones=zones,
        message=message,
    )


@router.post("/api/alerts/subscribe")
async def subscribe(sub: AlertSubscription) -> dict[str, str]:
    """Record a device's position (and optionally its active route)."""
    pool = db.pool()
    if pool is None:
        return {"status": "accepted", "detail": "no database; subscription not persisted"}

    route_json = (
        json.dumps({"type": "LineString", "coordinates": sub.active_route.coordinates})
        if sub.active_route
        else None
    )

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO alert_subscriptions
                (device_id, last_seen, radius_m, active_route, updated_at)
            VALUES ($1, ST_SetSRID(ST_MakePoint($2, $3), 4326), $4,
                    CASE WHEN $5::text IS NULL THEN NULL
                         ELSE ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($5), 4326))
                    END,
                    now())
            ON CONFLICT (device_id) DO UPDATE
               SET last_seen = EXCLUDED.last_seen,
                   radius_m = EXCLUDED.radius_m,
                   active_route = EXCLUDED.active_route,
                   updated_at = now()
            """,
            sub.device_id,
            sub.location.lon,
            sub.location.lat,
            sub.radius_m,
            route_json,
        )
    return {"status": "ok"}


@router.websocket("/ws/alerts")
async def alerts_socket(websocket: WebSocket) -> None:
    """Push the active-zone count every 30s. Cheap way to drive a live badge."""
    await websocket.accept()
    try:
        while True:
            pool = db.pool()
            count = 0
            if pool is not None:
                async with pool.acquire() as conn:
                    count = int(
                        await conn.fetchval(
                            "SELECT count(*) FROM flood_zones "
                            "WHERE expires IS NULL OR expires > now()"
                        )
                        or 0
                    )
            await websocket.send_json({"type": "flood_zone_count", "count": count})
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        log.info("alert socket closed: %s", exc)
