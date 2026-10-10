"""River gauges with their recent trend.

The sparkline comes from the `gauge_hourly` continuous aggregate when it exists,
falling back to a plain time_bucket over the hypertable.
"""

import logging

from fastapi import APIRouter, Query

from .. import db
from ..config import get_settings
from ..fixtures import fixture_gauges
from ..models import Gauge, GaugeReading, GaugeStatus, GaugeTrend
from .flood_zones import parse_bbox

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["gauges"])

_SITES_SQL = """
SELECT g.site_id, g.name, ST_Y(g.geom) AS lat, ST_X(g.geom) AS lon,
       g.flood_stage_ft, g.action_stage_ft,
       latest.gauge_height_ft AS current_ft
FROM gauge_sites g
LEFT JOIN LATERAL (
    SELECT gauge_height_ft
    FROM gauge_readings
    WHERE site_id = g.site_id AND gauge_height_ft IS NOT NULL
    ORDER BY time DESC
    LIMIT 1
) latest ON TRUE
WHERE ($1::double precision IS NULL
       OR ST_Intersects(g.geom, ST_MakeEnvelope($1, $2, $3, $4, 4326)))
LIMIT $5
"""

_CAGG_SERIES_SQL = """
SELECT site_id, bucket AS time, avg_ft AS gauge_height_ft
FROM gauge_hourly
WHERE site_id = ANY($1::text[]) AND bucket > now() - INTERVAL '24 hours'
ORDER BY site_id, bucket
"""

_RAW_SERIES_SQL = """
SELECT site_id,
       time_bucket('1 hour', time) AS time,
       avg(gauge_height_ft)        AS gauge_height_ft
FROM gauge_readings
WHERE site_id = ANY($1::text[]) AND time > now() - INTERVAL '24 hours'
GROUP BY site_id, time_bucket('1 hour', time)
ORDER BY site_id, 2
"""


def classify(
    current: float | None, flood_stage: float | None, action_stage: float | None
) -> GaugeStatus:
    if current is None:
        return GaugeStatus.UNKNOWN
    if flood_stage is not None and current >= flood_stage:
        return GaugeStatus.FLOOD
    if action_stage is not None and current >= action_stage:
        return GaugeStatus.ACTION
    return GaugeStatus.NORMAL


def trend_of(series: list[GaugeReading]) -> GaugeTrend:
    """Compare the last three hours against the three before them."""
    values = [r.gauge_height_ft for r in series if r.gauge_height_ft is not None]
    if len(values) < 4:
        return GaugeTrend.UNKNOWN
    recent = values[-3:]
    prior = values[-6:-3] or values[:-3]
    delta = (sum(recent) / len(recent)) - (sum(prior) / len(prior))
    if delta > 0.1:
        return GaugeTrend.RISING
    if delta < -0.1:
        return GaugeTrend.FALLING
    return GaugeTrend.STEADY


@router.get("/gauges", response_model=list[Gauge])
async def list_gauges(
    bbox: str | None = Query(None, examples=["-95.8,29.4,-95.0,30.2"]),
    limit: int = Query(200, ge=1, le=1000),
) -> list[Gauge]:
    settings = get_settings()
    pool = db.pool()

    if settings.use_fixtures or pool is None:
        return fixture_gauges()

    box = parse_bbox(bbox)
    args = (box[0], box[1], box[2], box[3]) if box else (None, None, None, None)

    async with pool.acquire() as conn:
        rows = await conn.fetch(_SITES_SQL, *args, limit)
        site_ids = [r["site_id"] for r in rows]

        series_rows = []
        if site_ids:
            try:
                series_rows = await conn.fetch(_CAGG_SERIES_SQL, site_ids)
            except Exception as exc:  # noqa: BLE001 - cagg may not exist yet
                log.info("gauge_hourly unavailable (%s); using raw readings", exc)
                series_rows = await conn.fetch(_RAW_SERIES_SQL, site_ids)

    by_site: dict[str, list[GaugeReading]] = {}
    for r in series_rows:
        by_site.setdefault(r["site_id"], []).append(
            GaugeReading(
                time=r["time"],
                gauge_height_ft=(
                    float(r["gauge_height_ft"]) if r["gauge_height_ft"] is not None else None
                ),
            )
        )

    out: list[Gauge] = []
    for r in rows:
        series = by_site.get(r["site_id"], [])
        current = float(r["current_ft"]) if r["current_ft"] is not None else None
        out.append(
            Gauge(
                site_id=r["site_id"],
                name=r["name"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                current_ft=current,
                flood_stage_ft=r["flood_stage_ft"],
                action_stage_ft=r["action_stage_ft"],
                status=classify(current, r["flood_stage_ft"], r["action_stage_ft"]),
                trend=trend_of(series),
                series=series,
            )
        )
    return out
