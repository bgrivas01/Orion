"""Ingest river gauges: site metadata (with flood stages) and live readings.

Two sources, because neither has everything:
  * NOAA NWPS bulk CSV  -> location + action/flood stage thresholds
  * USGS Water Services -> live gauge height readings

The USGS instantaneous-values feed has no flood-stage thresholds, and the NWPS
report has no live readings, so we join them on the USGS site id.
"""

import csv
import io
import logging
from datetime import datetime

import asyncpg
import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

NWPS_CSV = "https://water.noaa.gov/resources/downloads/reports/nwps_all_gauges_report.csv"
USGS_IV = "https://waterservices.usgs.gov/nwis/iv/"

# NWPS uses -9999 to mean "no threshold defined".
MISSING = -9000.0

# Gauge height, in feet.
PARAM_GAUGE_HEIGHT = "00065"


def _num(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return None if parsed <= MISSING else parsed


async def sync_sites(conn: asyncpg.Connection) -> int:
    """Refresh gauge_sites from the NWPS report. Run daily — thresholds rarely move."""
    settings = get_settings()
    states = set(settings.state_list)
    if not states:
        return 0

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            r = await client.get(NWPS_CSV)
    except httpx.HTTPError as exc:
        log.warning("NWPS gauge report fetch failed: %s", exc)
        return 0

    if r.status_code >= 400:
        log.warning("NWPS gauge report returned %s", r.status_code)
        return 0

    reader = csv.DictReader(io.StringIO(r.text))
    rows: list[tuple] = []
    for row in reader:
        if (row.get("state") or "").strip().upper() not in states:
            continue
        site_id = (row.get("usgs id") or "").strip()
        lat = _num(row.get("latitude"))
        lon = _num(row.get("longitude"))
        if not site_id or lat is None or lon is None:
            continue
        rows.append(
            (
                site_id,
                (row.get("location name") or site_id).strip(),
                lon,
                lat,
                _num(row.get("flood stage")),
                _num(row.get("action stage")),
                (row.get("state") or "").strip().upper(),
            )
        )

    if not rows:
        return 0

    await conn.executemany(
        """
        INSERT INTO gauge_sites
            (site_id, name, geom, flood_stage_ft, action_stage_ft, state_cd)
        VALUES ($1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), $5, $6, $7)
        ON CONFLICT (site_id) DO UPDATE
           SET name = EXCLUDED.name,
               geom = EXCLUDED.geom,
               flood_stage_ft = EXCLUDED.flood_stage_ft,
               action_stage_ft = EXCLUDED.action_stage_ft,
               state_cd = EXCLUDED.state_cd
        """,
        rows,
    )
    log.info("gauge site sync: %d site(s) upserted", len(rows))
    return len(rows)


async def ingest_readings(conn: asyncpg.Connection) -> int:
    """Pull the latest gauge heights for the configured states."""
    settings = get_settings()
    states = settings.state_list
    if not states:
        return 0

    inserted = 0
    async with httpx.AsyncClient(timeout=90) as client:
        for state in states:
            try:
                r = await client.get(
                    USGS_IV,
                    params={
                        "format": "json",
                        "stateCd": state,
                        "parameterCd": PARAM_GAUGE_HEIGHT,
                        "siteStatus": "active",
                    },
                )
            except httpx.HTTPError as exc:
                log.warning("USGS fetch failed for %s: %s", state, exc)
                continue

            if r.status_code >= 400:
                log.warning("USGS returned %s for %s", r.status_code, state)
                continue

            series = (r.json().get("value") or {}).get("timeSeries") or []
            rows: list[tuple] = []

            for ts in series:
                source = ts.get("sourceInfo") or {}
                codes = source.get("siteCode") or []
                if not codes:
                    continue
                site_id = codes[0].get("value")
                if not site_id:
                    continue

                for block in ts.get("values") or []:
                    for point in block.get("value") or []:
                        raw = point.get("value")
                        if raw in (None, "", "-999999"):
                            continue
                        try:
                            height = float(raw)
                        except ValueError:
                            continue
                        when = point.get("dateTime")
                        if not when:
                            continue
                        try:
                            stamp = datetime.fromisoformat(when)
                        except ValueError:
                            continue
                        rows.append((stamp, site_id, height))

            if not rows:
                continue

            # Only keep readings for gauges we know about, so the join in the
            # risk engine always has thresholds to compare against.
            known = {
                r["site_id"]
                for r in await conn.fetch(
                    "SELECT site_id FROM gauge_sites WHERE site_id = ANY($1::text[])",
                    list({row[1] for row in rows}),
                )
            }
            rows = [row for row in rows if row[1] in known]
            if not rows:
                continue

            await conn.executemany(
                """
                INSERT INTO gauge_readings (time, site_id, gauge_height_ft)
                VALUES ($1, $2, $3)
                ON CONFLICT (site_id, time) DO NOTHING
                """,
                rows,
            )
            inserted += len(rows)

    log.info("gauge reading ingest: %d reading(s) written", inserted)
    return inserted
