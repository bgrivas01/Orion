"""Active flood zones, as GeoJSON-ready polygons for the map overlay."""

import json
import logging

from fastapi import APIRouter, Query

from .. import db
from ..config import get_settings
from ..fixtures import fixture_flood_zones
from ..models import FloodZone, MultiPolygon
from ..services.avoid_set import severity_from_text

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["flood zones"])

_SQL = """
SELECT id, source, event, severity, headline,
       ST_AsGeoJSON(ST_Multi(geom)) AS gj,
       effective, expires
FROM flood_zones
WHERE (expires IS NULL OR expires > now())
  AND ($1::double precision IS NULL
       OR ST_Intersects(geom, ST_MakeEnvelope($1, $2, $3, $4, 4326)))
ORDER BY
    CASE severity
        WHEN 'extreme'  THEN 0
        WHEN 'severe'   THEN 1
        WHEN 'moderate' THEN 2
        WHEN 'minor'    THEN 3
        ELSE 4
    END
LIMIT $5
"""


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    """Parse 'minLon,minLat,maxLon,maxLat'."""
    if not bbox:
        return None
    try:
        parts = [float(p) for p in bbox.split(",")]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]


@router.get("/flood-zones", response_model=list[FloodZone])
async def list_flood_zones(
    bbox: str | None = Query(
        None,
        description="minLon,minLat,maxLon,maxLat — omit for every active zone.",
        examples=["-95.8,29.4,-95.0,30.2"],
    ),
    limit: int = Query(500, ge=1, le=2000),
) -> list[FloodZone]:
    settings = get_settings()
    pool = db.pool()

    if settings.use_fixtures or pool is None:
        return fixture_flood_zones()

    box = parse_bbox(bbox)
    args = (box[0], box[1], box[2], box[3]) if box else (None, None, None, None)

    async with pool.acquire() as conn:
        rows = await conn.fetch(_SQL, *args, limit)

    return [
        FloodZone(
            id=r["id"],
            source=r["source"],
            event=r["event"],
            severity=severity_from_text(r["severity"]),
            headline=r["headline"],
            geometry=MultiPolygon(coordinates=json.loads(r["gj"])["coordinates"]),
            effective=r["effective"],
            expires=r["expires"],
        )
        for r in rows
    ]
