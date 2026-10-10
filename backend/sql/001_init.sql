-- Orion schema: tables, hypertables, indexes.
-- Idempotent — safe to run on every boot. Runs fine inside one transaction.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;

-- Community observations: compatible with bloodproject/app.py's existing table.
-- Existing reports are retained; this only provisions fresh databases.
CREATE TABLE IF NOT EXISTS public.flood_reports (
    id BIGSERIAL PRIMARY KEY,
    location_name TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    water_depth_inches NUMERIC,
    severity TEXT,
    description TEXT,
    reported_at TIMESTAMPTZ DEFAULT now()
);

-- --------------------------------------------------------------------------- --
-- Gauge metadata (static, seeded from USGS + NWS flood-stage tables)
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS gauge_sites (
    site_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    flood_stage_ft  DOUBLE PRECISION,
    action_stage_ft DOUBLE PRECISION,
    state_cd        TEXT
);
CREATE INDEX IF NOT EXISTS gauge_sites_geom_idx ON gauge_sites USING GIST (geom);

-- --------------------------------------------------------------------------- --
-- Gauge readings — TIME SERIES, this is the TimescaleDB hypertable
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS gauge_readings (
    time            TIMESTAMPTZ NOT NULL,
    site_id         TEXT NOT NULL,
    gauge_height_ft DOUBLE PRECISION,
    discharge_cfs   DOUBLE PRECISION
);
SELECT create_hypertable('gauge_readings', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS gauge_readings_site_time_idx
    ON gauge_readings (site_id, time DESC);
-- One reading per site per timestamp; lets ingest use ON CONFLICT DO NOTHING.
CREATE UNIQUE INDEX IF NOT EXISTS gauge_readings_site_time_uniq
    ON gauge_readings (site_id, time);

-- --------------------------------------------------------------------------- --
-- Flood zones — GEOSPATIAL, this is the PostGIS side
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS flood_zones (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL DEFAULT 'nws',
    event       TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'unknown',
    headline    TEXT,
    geom        GEOMETRY(MultiPolygon, 4326) NOT NULL,
    effective   TIMESTAMPTZ,
    expires     TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS flood_zones_geom_idx ON flood_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS flood_zones_expires_idx ON flood_zones (expires);

-- Cached NWS zone polygons, for alerts that ship zone codes instead of geometry.
CREATE TABLE IF NOT EXISTS nws_zones (
    zone_id TEXT PRIMARY KEY,
    geom    GEOMETRY(MultiPolygon, 4326) NOT NULL,
    cached_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------- --
-- Elevation cache (Open Topo Data allows only 1000 calls/day, so cache hard)
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS elevation_cache (
    geohash     TEXT PRIMARY KEY,
    elevation_m DOUBLE PRECISION NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------- --
-- Route history — also a hypertable; powers demo stats and recent routes
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS route_requests (
    time        TIMESTAMPTZ NOT NULL,
    request_id  UUID NOT NULL,
    origin      GEOMETRY(Point, 4326),
    destination GEOMETRY(Point, 4326),
    chosen      TEXT,
    risk_score  DOUBLE PRECISION
);
SELECT create_hypertable('route_requests', 'time', if_not_exists => TRUE);

-- --------------------------------------------------------------------------- --
-- Mobile alert subscriptions
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS alert_subscriptions (
    device_id    TEXT PRIMARY KEY,
    last_seen    GEOMETRY(Point, 4326),
    radius_m     INTEGER NOT NULL DEFAULT 5000,
    active_route GEOMETRY(LineString, 4326),
    notified_zone_ids TEXT[] NOT NULL DEFAULT '{}',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS alert_subscriptions_geom_idx
    ON alert_subscriptions USING GIST (last_seen);
