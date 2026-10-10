"""Orion API entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import get_settings
from .routers import alerts, flood_zones, gauges, geocode, health, routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("orion")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    await db.connect()
    if db.pool() is not None:
        try:
            await db.apply_schema()
        except Exception as exc:  # noqa: BLE001 - never let schema issues block boot
            log.error("could not apply schema: %s", exc)

    scheduler = None
    if settings.enable_scheduler and db.pool() is not None:
        from .ingest.scheduler import start_scheduler

        scheduler = start_scheduler()

    if settings.use_fixtures:
        log.warning("USE_FIXTURES=true — serving demo data instead of live APIs")
    if not settings.ors_api_key:
        log.warning("ORS_API_KEY is not set — routing will fall back to fixtures")

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await db.disconnect()


app = FastAPI(
    title="Orion API",
    version="0.1.0",
    summary="Flood-aware safest-route routing.",
    description=(
        "Fuses live NWS flood alerts, USGS river gauges and terrain elevation with "
        "OpenRouteService routing to rank routes by flood risk.\n\n"
        "**Design note:** ORS `avoid_polygons` is unreliable, so every route returned "
        "by ORS is independently verified against flood polygons in PostGIS. Trust "
        "`avoidance_verified`, never `avoidance_requested`."
    ),
    lifespan=lifespan,
)

# Hackathon-wide open CORS: Next.js dev server, Expo Go and tunnelled demo URLs
# all need in, and the API serves only public data.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(routes.router)
app.include_router(flood_zones.router)
app.include_router(gauges.router)
app.include_router(geocode.router)
app.include_router(alerts.router)
