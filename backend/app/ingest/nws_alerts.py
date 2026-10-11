"""Ingest active NWS flood alerts into flood_zones.

api.weather.gov is free and keyless but *requires* a descriptive User-Agent.

Not every alert carries geometry: county/zone-based products ship `affectedZones`
URLs instead. For those we fetch the zone polygons (cached in nws_zones, since
they never change) and union them.
"""

import json
import logging
from datetime import datetime
from typing import Any

import asyncpg
import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

API = "https://api.weather.gov"
# weather.gov blocks requests without an identifying User-Agent.
HEADERS = {
    "User-Agent": "Orion flood-routing (hackathon project; contact: orion@example.com)",
    "Accept": "application/geo+json",
}

FLOOD_EVENTS = {
    "Flash Flood Warning",
    "Flash Flood Statement",
    "Flood Warning",
    "Flood Advisory",
    "Flood Watch",
    "Flash Flood Watch",
    "Coastal Flood Warning",
    "Coastal Flood Advisory",
    "Coastal Flood Watch",
}

_UPSERT = """
INSERT INTO flood_zones
    (id, source, event, severity, headline, geom, effective, expires, ingested_at)
VALUES ($1, 'nws', $2, $3, $4,
        ST_Multi(ST_CollectionExtract(
            ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($5), 4326)), 3)),
        $6, $7, now())
ON CONFLICT (id) DO UPDATE
   SET event = EXCLUDED.event,
       severity = EXCLUDED.severity,
       headline = EXCLUDED.headline,
       geom = EXCLUDED.geom,
       effective = EXCLUDED.effective,
       expires = EXCLUDED.expires,
       ingested_at = now()
"""


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse NWS ISO 8601 timestamps; missing/invalid values become SQL NULL.

    Require an explicit timezone rather than guessing one for malformed feed
    data. Preserve supplied offsets; asyncpg handles TIMESTAMPTZ conversion.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            raise ValueError("expected an ISO 8601 string")
        if parsed.utcoffset() is None:
            raise ValueError("timestamp has no timezone")
        return parsed
    except (ValueError, TypeError, OverflowError):
        log.warning("invalid NWS timestamp %r; treating as missing", value)
        return None


async def _zone_geometry(
    client: httpx.AsyncClient, conn: asyncpg.Connection, zone_url: str
) -> dict[str, Any] | None:
    """Fetch (and cache) the polygon for a zone-coded alert."""
    zone_id = zone_url.rstrip("/").split("/")[-1]

    cached = await conn.fetchval(
        "SELECT ST_AsGeoJSON(geom) FROM nws_zones WHERE zone_id = $1", zone_id
    )
    if cached:
        return json.loads(cached)

    try:
        r = await client.get(zone_url, headers=HEADERS, timeout=20)
        if r.status_code >= 400:
            return None
        geometry = (r.json() or {}).get("geometry")
    except httpx.HTTPError as exc:
        log.debug("zone fetch failed for %s: %s", zone_id, exc)
        return None

    if not geometry:
        return None

    try:
        await conn.execute(
            """
            INSERT INTO nws_zones (zone_id, geom)
            VALUES ($1, ST_Multi(ST_CollectionExtract(
                        ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON($2), 4326)), 3)))
            ON CONFLICT (zone_id) DO NOTHING
            """,
            zone_id,
            json.dumps(geometry),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("could not cache zone %s: %s", zone_id, exc)

    return geometry


def _merge(geometries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Combine several polygons into one GeoJSON MultiPolygon."""
    coords: list[Any] = []
    for g in geometries:
        if g.get("type") == "Polygon":
            coords.append(g["coordinates"])
        elif g.get("type") == "MultiPolygon":
            coords.extend(g["coordinates"])
    if not coords:
        return None
    return {"type": "MultiPolygon", "coordinates": coords}


async def ingest(conn: asyncpg.Connection) -> int:
    """Pull active flood alerts for the configured states. Returns rows written."""
    settings = get_settings()
    states = settings.state_list
    if not states:
        return 0

    written = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for state in states:
            try:
                r = await client.get(
                    f"{API}/alerts/active",
                    params={"area": state, "status": "actual"},
                    headers=HEADERS,
                )
            except httpx.HTTPError as exc:
                log.warning("NWS alerts fetch failed for %s: %s", state, exc)
                continue

            if r.status_code >= 400:
                log.warning("NWS alerts returned %s for %s", r.status_code, state)
                continue

            for feature in (r.json().get("features") or []):
                props = feature.get("properties") or {}
                event = props.get("event") or ""
                if event not in FLOOD_EVENTS:
                    continue

                alert_id = props.get("id") or feature.get("id")
                if not alert_id:
                    continue

                geometry = feature.get("geometry")
                if not geometry:
                    # Zone-coded alert: assemble the polygon from its zones.
                    zone_urls = props.get("affectedZones") or []
                    parts = []
                    for url in zone_urls[:12]:  # keep the fan-out bounded
                        zg = await _zone_geometry(client, conn, url)
                        if zg:
                            parts.append(zg)
                    geometry = _merge(parts)

                if not geometry:
                    log.debug("no geometry for alert %s (%s)", alert_id, event)
                    continue

                try:
                    await conn.execute(
                        _UPSERT,
                        alert_id,
                        event,
                        (props.get("severity") or "unknown").lower(),
                        props.get("headline"),
                        json.dumps(geometry),
                        _parse_timestamp(props.get("effective")),
                        _parse_timestamp(props.get("expires"))
                        or _parse_timestamp(props.get("ends")),
                    )
                    written += 1
                except Exception as exc:  # noqa: BLE001 - one bad polygon must not stop the run
                    log.warning("could not store alert %s: %s", alert_id, exc)

    log.info("NWS alert ingest: %d zone(s) written", written)
    return written


async def purge_expired(conn: asyncpg.Connection) -> int:
    """Drop alerts that expired over a day ago. Recent ones stay for history."""
    result = await conn.execute(
        "DELETE FROM flood_zones "
        "WHERE source = 'nws' AND expires IS NOT NULL AND expires < now() - INTERVAL '1 day'"
    )
    return int(result.split()[-1]) if result.startswith("DELETE") else 0
