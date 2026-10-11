"""Liveness + dependency check. First thing to hit when something looks wrong."""

from fastapi import APIRouter

from .. import db
from ..config import get_settings
from ..models import HealthResponse, LatLng
from ..services import ors as ors_client

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    details: list[str] = []

    database = postgis = timescale = False
    active_zones: int | None = None

    p = db.pool()
    if p is None:
        details.append("DATABASE_URL not configured")
    else:
        try:
            async with p.acquire() as conn:
                database = bool(await conn.fetchval("SELECT 1"))
                exts = await conn.fetch(
                    "SELECT extname FROM pg_extension WHERE extname = ANY($1::text[])",
                    ["postgis", "timescaledb"],
                )
                names = {r["extname"] for r in exts}
                postgis = "postgis" in names
                timescale = "timescaledb" in names
                active_zones = await conn.fetchval(
                    "SELECT count(*) FROM flood_zones "
                    "WHERE expires IS NULL OR expires > now()"
                )
        except Exception as exc:  # noqa: BLE001
            details.append(f"database error: {exc}")

    ors = False
    if not settings.ors_api_key:
        details.append("ORS_API_KEY not configured")
    else:
        try:
            # The public API does not expose /v2/health. Exercise both services
            # with a small fixed query; this consumes normal API quota.
            await ors_client.directions(
                LatLng(lat=29.7604, lon=-95.3698),
                LatLng(lat=29.7634, lon=-95.3698),
            )
            await ors_client.geocode("Houston", limit=1)
            ors = True
        except ors_client.ORSError as exc:
            details.append(str(exc))

    ok = database and ors and postgis
    return HealthResponse(
        status="ok" if ok else "degraded",
        database=database,
        ors=ors,
        postgis=postgis,
        timescaledb=timescale,
        active_flood_zones=active_zones,
        detail="; ".join(details) or None,
    )
