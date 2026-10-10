"""Background ingest jobs, run in-process by APScheduler.

One process keeps the hackathon deploy simple. Intervals are well inside every
upstream rate limit.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .. import db
from . import nws_alerts, usgs_gauges

log = logging.getLogger(__name__)


async def _run(name: str, coro_factory) -> None:
    pool = db.pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await coro_factory(conn)
    except Exception as exc:  # noqa: BLE001 - a failed run must not kill the scheduler
        log.error("ingest job %s failed: %s", name, exc)


async def refresh_alerts() -> None:
    await _run("nws_alerts", nws_alerts.ingest)
    await _run("purge_expired", nws_alerts.purge_expired)


async def refresh_readings() -> None:
    await _run("usgs_readings", usgs_gauges.ingest_readings)


async def refresh_sites() -> None:
    await _run("gauge_sites", usgs_gauges.sync_sites)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Flood alerts move fast; this is the one that matters during an event.
    scheduler.add_job(refresh_alerts, "interval", minutes=5, next_run_time=None, id="alerts")
    # USGS publishes instantaneous values every 15 minutes.
    scheduler.add_job(refresh_readings, "interval", minutes=15, id="readings")
    # Thresholds and station lists barely change.
    scheduler.add_job(refresh_sites, "interval", hours=24, id="sites")

    scheduler.start()

    # Prime everything immediately so the first request has data to work with.
    scheduler.add_job(refresh_sites, id="sites_now")
    scheduler.add_job(refresh_alerts, id="alerts_now")
    scheduler.add_job(refresh_readings, id="readings_now")

    log.info("ingest scheduler started")
    return scheduler
