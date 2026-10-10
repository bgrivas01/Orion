"""Read the existing Tiger Cloud flood_reports table used by bloodproject/app.py."""

import logging

import asyncpg
from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..config import get_settings
from ..models import FloodReport

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["flood reports"])

_SQL = """
SELECT id::text AS id, location_name, latitude, longitude,
       water_depth_inches, severity, description, reported_at
FROM public.flood_reports
ORDER BY reported_at DESC NULLS LAST, id DESC
LIMIT $1
"""


@router.get("/flood-reports", response_model=list[FloodReport])
async def list_flood_reports(limit: int = Query(100, ge=1, le=500)) -> list[FloodReport]:
    # Never present demonstration observations as actual community reports.
    if get_settings().use_fixtures:
        return []
    pool = db.pool()
    if pool is None:
        raise HTTPException(503, "Flood reports are unavailable: database is not connected.")
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SQL, limit)
        return [FloodReport(**dict(row)) for row in rows]
    except (asyncpg.PostgresError, OSError, TimeoutError):
        log.exception("Could not load flood reports")
        raise HTTPException(503, "Flood reports are temporarily unavailable.") from None
